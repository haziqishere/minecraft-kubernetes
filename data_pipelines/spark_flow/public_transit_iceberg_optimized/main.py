"""
Optimized Prefect flow to ingest public transit JSONL data from S3 into Iceberg table.
This version includes all the advanced Iceberg optimizations from the standalone script.

Data flow:
    Kafka Producer -> Kafka -> Kafka Connect -> S3 (JSONL) -> This flow -> Iceberg (Glue Catalog)

Features:
- Advanced data quality validation
- Deduplication
- Optimized Iceberg table with bucketing and bloom filters
- Performance optimizations
- AWS resource validation and graceful error handling
"""
import os
from pathlib import Path
from prefect.cache_policies import NO_CACHE
from datetime import datetime, timedelta
import pytz

from prefect import task, flow, get_run_logger
from prefect.cache_policies import NONE
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_unixtime, to_timestamp, current_timestamp,
    when, lit, row_number, count
)
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType
from pyspark.sql.window import Window

from utilities.config_utils import get_json_config
from utilities.aws_utils import retrieve_credentials


def define_schema():
    """Define schema matching the actual JSON structure"""
    position_schema = StructType([
        StructField("bearing", DoubleType(), True),
        StructField("latitude", DoubleType(), True),
        StructField("speed", DoubleType(), True),
        StructField("longitude", DoubleType(), True)
    ])
    
    vehicle_schema = StructType([
        StructField("license_plate", StringType(), True),
        StructField("id", StringType(), True)
    ])
    
    trip_schema = StructType([
        StructField("start_time", StringType(), True),
        StructField("trip_id", StringType(), True),
        StructField("route_id", StringType(), True),
        StructField("start_date", StringType(), True)
    ])
    
    return StructType([
        StructField("ingestion_timestamp", StringType(), True),
        StructField("trip", trip_schema, True),
        StructField("feed_timestamp", LongType(), True),
        StructField("producer_version", StringType(), True),
        StructField("vehicle_timestamp", LongType(), True),
        StructField("position", position_schema, True),
        StructField("entity_id", StringType(), True),
        StructField("category", StringType(), True),
        StructField("vehicle", vehicle_schema, True)
    ])


@task
def validate_aws_prerequisites():
    """Validate AWS prerequisites before starting the pipeline"""
    logger = get_run_logger()
    logger.info("Validating AWS prerequisites...")
    
    # Check AWS credentials
    try:
        import boto3
        credentials = retrieve_credentials()
        sts_client = boto3.client(
            'sts',
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"]
        )
        identity = sts_client.get_caller_identity()
        logger.info(f"AWS credentials validated for account: {identity.get('Account', 'Unknown')}")
    except Exception as e:
        logger.error(f"AWS credentials validation failed: {str(e)}")
        raise ValueError("AWS credentials not properly configured. Please configure AWS CLI or environment variables.")
    
    # Check AWS region
    aws_region = os.getenv("AWS_REGION", "ap-southeast-1")
    logger.info(f"Using AWS region: {aws_region}")
    
    return True


@task
def create_spark_session(warehouse_path: str):
    """Create Spark session with Iceberg and S3 configuration"""
    logger = get_run_logger()
    logger.info("Creating Spark session with advanced Iceberg optimizations")

    # Get AWS credentials and account ID
    import boto3
    credentials = retrieve_credentials()
    aws_region = os.getenv("AWS_REGION", "ap-southeast-1")

    # Get AWS account ID from STS
    sts_client = boto3.client(
        'sts',
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials.get("SessionToken"),
        region_name=aws_region
    )
    account_id = sts_client.get_caller_identity()["Account"]

    spark_builder = (SparkSession.builder
        .appName("JSON to Iceberg Pipeline - Production")
        # Iceberg extensions
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        # Glue catalog configuration
        .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.glue_catalog.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
        .config("spark.sql.catalog.glue_catalog.warehouse", warehouse_path)
        .config("spark.sql.catalog.glue_catalog.region", aws_region)
        .config("spark.sql.catalog.glue_catalog.glue.account-id", account_id)
        # Iceberg S3FileIO credentials (Iceberg uses its own S3 client)
        .config("spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
        .config("spark.sql.catalog.glue_catalog.s3.access-key-id", credentials["AccessKeyId"])
        .config("spark.sql.catalog.glue_catalog.s3.secret-access-key", credentials["SecretAccessKey"])
        .config("spark.sql.catalog.glue_catalog.s3.region", aws_region)
        # Hadoop S3A configuration (for reading source JSON files)
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.hadoop.fs.s3a.path.style.access", "false")
        .config("spark.hadoop.fs.s3a.access.key", credentials["AccessKeyId"])
        .config("spark.hadoop.fs.s3a.secret.key", credentials["SecretAccessKey"])
        .config("spark.hadoop.fs.s3a.endpoint", f"s3.{aws_region}.amazonaws.com")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "true")
        .config("spark.hadoop.fs.s3a.fast.upload", "true")
        .config("spark.hadoop.fs.s3a.buffer.dir", "/tmp")
        # Fix for Hadoop 3.3.6 S3A compatibility issues
        .config("spark.hadoop.fs.s3a.input.fadvice", "disabled")
        .config("spark.hadoop.fs.s3a.experimental.input.fadvise", "false")
        .config("spark.hadoop.fs.s3a.statistics.enabled", "false")
        .config("spark.hadoop.fs.s3a.attempts.maximum", "10")
        .config("spark.hadoop.fs.s3a.retry.limit", "10")
        .config("spark.hadoop.fs.s3a.retry.interval", "5000")
        # Performance optimizations
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
    )

    # Add session token configuration if using temporary credentials
    session_token = credentials.get("SessionToken")
    if session_token:
        logger.info("Using temporary credentials with session token")
        spark_builder = (spark_builder
            # S3A session token
            .config("spark.hadoop.fs.s3a.session.token", session_token)
            .config("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.TemporaryAWSCredentialsProvider")
            # Iceberg S3FileIO session token
            .config("spark.sql.catalog.glue_catalog.s3.session-token", session_token)
        )
    else:
        logger.info("Using static credentials (no session token)")
        spark_builder = spark_builder.config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"
        )

    try:
        spark = spark_builder.getOrCreate()
        logger.info("Spark session created successfully")
        
        # Test Glue catalog connection
        try:
            spark.sql("SHOW DATABASES IN glue_catalog")
            logger.info("Glue catalog connection successful")
        except Exception as e:
            logger.warning(f"Glue catalog connection failed: {str(e)}")
            logger.warning("Please ensure Glue database 'public_transport' exists and IAM permissions are correct")
            raise ValueError("Glue catalog connection failed. Check AWS setup guide in doc/AWS_Glue_Iceberg_Setup.md")
        
        return spark
    except Exception as e:
        logger.error(f"Failed to create Spark session: {str(e)}")
        raise


@task(cache_policy=NONE)
def create_iceberg_table_if_not_exists(spark: SparkSession, table_name: str, warehouse_path: str):
    """Create Iceberg table with optimized schema, bucketing, and bloom filters if it doesn't exist"""
    logger = get_run_logger()
    logger.info(f"Creating optimized Iceberg table: {table_name}")
    
    # First, ensure the database exists
    try:
        database_name = table_name.split('.')[1]  # Extract database name from glue_catalog.public_transport.vehicle_positions
        spark.sql(f"CREATE DATABASE IF NOT EXISTS glue_catalog.{database_name}")
        logger.info(f"Database {database_name} ensured to exist")
    except Exception as e:
        logger.error(f"Failed to create database: {str(e)}")
        raise ValueError(f"Failed to create Glue database. Please check IAM permissions and Glue setup. Error: {str(e)}")
    
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        vehicle_id STRING,
        license_plate STRING,
        route_id STRING,
        trip_id STRING,
        start_date STRING,
        start_time STRING,
        start_date_dt DATE,
        start_time_formatted STRING,
        latitude DOUBLE,
        longitude DOUBLE,
        bearing DOUBLE,
        speed DOUBLE,
        vehicle_timestamp BIGINT,
        feed_timestamp BIGINT,
        category STRING,
        ingestion_timestamp STRING,
        producer_version STRING,
        vehicle_timestamp_dt TIMESTAMP,
        feed_timestamp_dt TIMESTAMP,
        ingestion_timestamp_dt TIMESTAMP,
        processing_timestamp TIMESTAMP,
        is_valid_coordinates BOOLEAN,
        is_valid_speed BOOLEAN,
        is_valid_bearing BOOLEAN,
        is_complete_record BOOLEAN,
        data_quality_score INT
    )
    USING iceberg
    PARTITIONED BY (start_date_dt, bucket(300, route_id))
    LOCATION '{warehouse_path}/public_transport/vehicle_positions'
    TBLPROPERTIES (
        'write.format.default' = 'parquet',
        'write.metadata.compression-codec' = 'gzip',
        'write.parquet.bloom-filter-enabled.column.category' = 'true',
        'write.parquet.bloom-filter-max-bytes' = '1048576',
        'write.distribution-mode' = 'hash',
        'commit.retry.num-retries' = '3',
        'format-version' = '2'
    )
    """
    
    try:
        spark.sql(create_table_sql)
        logger.info(f"Table {table_name} created or already exists")
        logger.info("Table features: Date partitioning + 300 route_id buckets + category bloom filters")
        
        # Verify table was created successfully
        table_info = spark.sql(f"DESCRIBE TABLE {table_name}")
        logger.info("Table schema verified successfully")
        
    except Exception as e:
        logger.error(f"Failed to create Iceberg table: {str(e)}")
        raise ValueError(f"Iceberg table creation failed. Please check S3 permissions and Lake Formation setup. Error: {str(e)}")


@task
def build_hourly_input_path(base_path: str) -> str:
    """
    Build S3 input path for recent hourly partitions.
    
    Args:
        base_path: Base S3 path (e.g., s3a://public-transport-dataset/raw)
    
    Returns:
        S3 path pattern for reading data
    """
    logger = get_run_logger()
    
    # Use Malaysia timezone (UTC+8) to match local time
    malaysia_tz = pytz.timezone('Asia/Kuala_Lumpur')
    now = datetime.now(malaysia_tz)

    dt = now - timedelta(hours=1)
    clean_base_path = base_path.rstrip('/')
    path = f"{clean_base_path}/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/hour={dt.hour:02d}/"
    logger.info(f"s3 input path for hourly partitioning: {path}")
    return path


@task(cache_policy=NO_CACHE, task_run_name="read-and-transform-data")
def read_and_transform_data(spark: SparkSession, input_path: str):
    """Read JSON files from S3 and transform with flattening and timestamp conversion"""
    logger = get_run_logger()
    logger.info(f"Reading JSON files from {input_path}")
    
    # Define schema
    schema = define_schema()
    
    try:
        # Read JSON files from S3
        df_raw = spark.read.schema(schema).json(input_path)
        
        initial_count = df_raw.count()
        logger.info(f"Loaded {initial_count} raw records")
        
        if initial_count == 0:
            logger.warning(f"No data found at {input_path}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to read data from S3: {str(e)}")
        raise ValueError(f"S3 read failed. Please check S3 bucket existence and permissions. Error: {str(e)}")
    
    # Flatten the nested structure
    df_flattened = df_raw.select(
        col("entity_id").alias("vehicle_id"),
        col("vehicle.license_plate"),
        col("trip.route_id"),
        col("trip.trip_id"),
        col("trip.start_date"),
        col("trip.start_time"),
        col("position.latitude"),
        col("position.longitude"),
        col("position.bearing"),
        col("position.speed"),
        col("vehicle_timestamp"),
        col("feed_timestamp"),
        col("category"),
        col("ingestion_timestamp"),
        col("producer_version")
    )
    
    # Convert timestamps and dates
    df_with_timestamps = df_flattened.withColumn(
        "vehicle_timestamp_dt", 
        from_unixtime(col("vehicle_timestamp")).cast("timestamp")
    ).withColumn(
        "feed_timestamp_dt", 
        from_unixtime(col("feed_timestamp")).cast("timestamp")
    ).withColumn(
        "ingestion_timestamp_dt",
        to_timestamp(col("ingestion_timestamp"))
    ).withColumn(
        "processing_timestamp",
        current_timestamp()
    ).withColumn(
        "start_date_dt",
        to_timestamp(col("start_date"), "yyyyMMdd").cast("date")
    ).withColumn(
        "start_time_formatted",
        to_timestamp(col("start_time"), "HH:mm:ss").cast("timestamp").cast("string")
    )
    
    logger.info(f"Transformed {df_with_timestamps.count()} records")
    return df_with_timestamps


@task(cache_policy=NONE)
def validate_data_quality(df):
    """Perform data quality checks and add quality flags"""
    logger = get_run_logger()
    logger.info("Running data quality checks...")
    
    # Add data quality flags
    df_validated = df.withColumn(
        "is_valid_coordinates",
        (col("latitude").between(-90, 90)) & (col("longitude").between(-180, 180))
    ).withColumn(
        "is_valid_speed",
        (col("speed").isNotNull()) & (col("speed") >= 0) & (col("speed") <= 150)
    ).withColumn(
        "is_valid_bearing",
        (col("bearing").isNull()) | (col("bearing").between(0, 360))
    ).withColumn(
        "is_complete_record",
        col("vehicle_id").isNotNull() & 
        col("route_id").isNotNull() & 
        col("trip_id").isNotNull()
    ).withColumn(
        "data_quality_score",
        (col("is_valid_coordinates").cast("int") +
         col("is_valid_speed").cast("int") +
         col("is_valid_bearing").cast("int") +
         col("is_complete_record").cast("int"))
    )
    
    # Log quality metrics
    total_records = df_validated.count()
    valid_coords = df_validated.filter(col("is_valid_coordinates")).count()
    valid_speed = df_validated.filter(col("is_valid_speed")).count()
    complete_records = df_validated.filter(col("is_complete_record")).count()
    
    logger.info(f"Total records: {total_records}")
    logger.info(f"Valid coordinates: {valid_coords} ({100*valid_coords/total_records:.2f}%)")
    logger.info(f"Valid speed: {valid_speed} ({100*valid_speed/total_records:.2f}%)")
    logger.info(f"Complete records: {complete_records} ({100*complete_records/total_records:.2f}%)")
    
    return df_validated


@task(cache_policy=NONE)
def deduplicate_records(df):
    """Remove duplicate records based on vehicle_id and timestamp"""
    logger = get_run_logger()
    logger.info("Deduplicating records...")
    
    # Define window for deduplication (keep latest record per vehicle_id and timestamp)
    window_spec = Window.partitionBy("vehicle_id", "vehicle_timestamp").orderBy(col("ingestion_timestamp_dt").desc())
    
    df_deduped = df.withColumn("row_num", row_number().over(window_spec)) \
                   .filter(col("row_num") == 1) \
                   .drop("row_num")
    
    original_count = df.count()
    deduped_count = df_deduped.count()
    duplicates = original_count - deduped_count
    
    logger.info(f"Removed {duplicates} duplicate records ({100*duplicates/original_count:.2f}%)")
    
    return df_deduped


@task(cache_policy=NONE)
def write_to_iceberg_optimized(df, output_table: str):
    """Write to Iceberg table with optimized partitioning and bloom filters"""
    logger = get_run_logger()
    
    # Show sample data
    logger.info("Sample processed data:")
    df.show(5, truncate=False)
    
    final_count = df.count()
    logger.info(f"Writing {final_count} records to Iceberg table")
    
    # Write to Iceberg table with optimized partitioning and bloom filters
    df.write \
        .format("iceberg") \
        .mode("append") \
        .option("write.format.default", "parquet") \
        .option("write.metadata.compression-codec", "gzip") \
        .option("write.parquet.bloom-filter-enabled.column.category", "true") \
        .option("write.parquet.bloom-filter-max-bytes", "1048576") \
        .partitionBy("start_date_dt") \
        .option("write.distribution-mode", "hash") \
        .sortBy("route_id") \
        .saveAsTable(output_table)
    
    logger.info("Successfully wrote to Iceberg table!")
    return final_count


@task(cache_policy=NONE)
def stop_spark_session(spark: SparkSession):
    """Stop Spark session"""
    logger = get_run_logger()
    spark.stop()
    logger.info("Spark session stopped")


@flow(name="public-transit-iceberg-optimized-ingest")
def transit_iceberg_optimized_pipeline(
    input_path: str = "s3a://public-transport-dataset/raw/transit-positions/",
    output_table: str = "glue_catalog.public_transport.vehicle_positions",
    enable_validation: bool = True,
    enable_deduplication: bool = True,
    min_quality_score: int = 3,
    use_hourly_partitions: bool = True
):
    """
    Optimized pipeline for ingesting public transit data to Iceberg with advanced features.
    
    Features:
    - AWS prerequisites validation
    - Data quality validation with scoring
    - Record deduplication
    - Optimized Iceberg table with bucketing and bloom filters
    - Performance optimizations
    - Graceful error handling for missing AWS resources
    - Hourly partition support for scheduled runs
    
    Args:
        input_path: Base S3 path to JSON files
        output_table: Fully qualified Iceberg table name
        enable_validation: Whether to run data quality checks
        enable_deduplication: Whether to remove duplicates
        min_quality_score: Minimum quality score (0-4) to include record
        use_hourly_partitions: Whether to use hourly partition paths
    """
    logger = get_run_logger()
    
    # Load configuration
    config_path = Path(__file__).parent / "config.json"
    config_data = get_json_config(config_path)
    
    # Use config values or defaults
    input_path = config_data.get("s3_raw_path", "s3a://public-transport-dataset/raw/transit-positions/")
    warehouse_path = config_data.get("s3_warehouse_path", "s3a://public-transport-dataset/warehouse/")
    output_table = config_data.get("iceberg_table", "glue_catalog.public_transport.vehicle_positions")
    
    logger.info(f"Starting optimized transit Iceberg ingest pipeline")
    logger.info(f"Base Input: {input_path} -> Output: {output_table}")
    logger.info(f"Warehouse: {warehouse_path}")
    logger.info(f"Validation: {enable_validation}, Deduplication: {enable_deduplication}")
    
    spark = None
    try:
        # Step 1: Validate AWS prerequisites
        validate_aws_prerequisites()
        
        # Step 2: Create Spark session
        spark = create_spark_session(warehouse_path)
        
        # Step 3: Ensure table exists with optimizations
        create_iceberg_table_if_not_exists(spark, output_table, warehouse_path)
        
        # Step 4: Build input path (hourly or regular)
        if use_hourly_partitions:
            actual_input_path = build_hourly_input_path(input_path)
        else:
            actual_input_path = input_path
        
        # Step 5: Read and transform data
        df_transformed = read_and_transform_data(spark, actual_input_path)
        
        # Handle case where no data is found
        if df_transformed is None:
            logger.warning("No data to process. Pipeline completed with 0 records.")
            return {
                "status": "success",
                "input_records": 0,
                "output_records": 0,
                "retention_rate": 0.0,
                "message": "No data found at input path"
            }
        
        # Step 6: Apply data quality checks if enabled
        if enable_validation:
            df_processed = validate_data_quality(df_transformed)
            
            # Filter by minimum quality score
            df_processed = df_processed.filter(col("data_quality_score") >= min_quality_score)
            filtered_count = df_processed.count()
            logger.info(f"Retained {filtered_count} records after quality filtering (score >= {min_quality_score})")
        else:
            df_processed = df_transformed
            logger.info("Skipping data quality validation")
        
        # Step 7: Apply deduplication if enabled
        if enable_deduplication:
            df_processed = deduplicate_records(df_processed)
        else:
            logger.info("Skipping deduplication")
        
        # Step 8: Write to Iceberg with optimizations
        final_count = write_to_iceberg_optimized(df_processed, output_table)
        
        logger.info(f"Pipeline completed successfully!")
        logger.info(f"Summary: {df_transformed.count()} input -> {final_count} output")
        
        return {
            "status": "success",
            "input_records": df_transformed.count(),
            "output_records": final_count,
            "retention_rate": final_count / df_transformed.count() if df_transformed.count() > 0 else 0
        }
        
    except ValueError as ve:
        # Handle known configuration/setup errors
        logger.error(f"Configuration error: {str(ve)}")
        logger.error("Please refer to doc/AWS_Glue_Iceberg_Setup.md for setup instructions")
        raise
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
        raise
    finally:
        if spark:
            stop_spark_session(spark)