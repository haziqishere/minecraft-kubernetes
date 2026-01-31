"""
Prefect flow to ingest public transit JSONL data from S3 into Iceberg table.

Data flow:
    Kafka Producer -> Kafka -> Kafka Connect -> S3 (JSONL) -> This flow -> Iceberg (Glue Catalog)

Schedule: Runs hourly to process new data partitions.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

from prefect import task, flow, get_run_logger
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType
from pyspark.sql.functions import col, to_timestamp, from_unixtime

from utilities.config_utils import get_json_config
from utilities.aws_utils import retrieve_credentials


# Schema matching the nested JSON from Kafka producer (via Kafka Connect)
TRIP_SCHEMA = StructType([
    StructField("trip_id", StringType(), True),
    StructField("start_time", StringType(), True),
    StructField("start_date", StringType(), True),
    StructField("route_id", StringType(), True),
])

POSITION_SCHEMA = StructType([
    StructField("latitude", DoubleType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("bearing", DoubleType(), True),
    StructField("speed", DoubleType(), True),
])

VEHICLE_SCHEMA = StructType([
    StructField("id", StringType(), True),
    StructField("license_plate", StringType(), True),
])

RAW_SCHEMA = StructType([
    StructField("entity_id", StringType(), True),
    StructField("trip", TRIP_SCHEMA, True),
    StructField("position", POSITION_SCHEMA, True),
    StructField("vehicle", VEHICLE_SCHEMA, True),
    StructField("vehicle_timestamp", LongType(), True),
    StructField("feed_timestamp", LongType(), True),
    StructField("category", StringType(), True),
    StructField("ingestion_timestamp", StringType(), True),
    StructField("producer_version", StringType(), True),
])


@task
def create_spark_session(warehouse_path: str):
    """Create Spark session with Iceberg and Glue catalog configuration"""
    logger = get_run_logger()
    logger.info("Creating Spark session with Iceberg/Glue configuration")

    aws_credentials = retrieve_credentials()

    spark = SparkSession.builder \
        .appName("TransitIcebergIngest") \
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions") \
        .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog") \
        .config("spark.sql.catalog.glue_catalog.type", "glue") \
        .config("spark.sql.catalog.glue_catalog.warehouse", warehouse_path) \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .config("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider") \
        .config("spark.hadoop.fs.s3a.access.key", aws_credentials["AWS_ACCESS_KEY_ID"]) \
        .config("spark.hadoop.fs.s3a.secret.key", aws_credentials["AWS_SECRET_ACCESS_KEY"]) \
        .config("spark.sql.parquet.enableVectorizedReader", "true") \
        .config("spark.sql.parquet.columnarReaderBatchSize", "1024") \
        .config("spark.sql.parquet.filterPushdown", "true") \
        .getOrCreate()

    logger.info("Spark session created successfully")
    return spark


@task
def ensure_table_exists(spark: SparkSession):
    """Create Iceberg table if it doesn't exist"""
    logger = get_run_logger()
    logger.info("Ensuring Iceberg table exists")

    spark.sql("""
    CREATE TABLE IF NOT EXISTS glue_catalog.public_transport.vehicle_positions (
        entity_id STRING,
        vehicle_id STRING,
        license_plate STRING,
        route_id STRING,
        trip_id STRING,
        trip_start_time STRING,
        trip_start_date STRING,
        latitude DOUBLE,
        longitude DOUBLE,
        bearing DOUBLE,
        speed DOUBLE,
        vehicle_timestamp LONG,
        feed_timestamp LONG,
        category STRING,
        ingestion_timestamp STRING,
        event_time TIMESTAMP
    ) USING iceberg
    PARTITIONED BY (days(event_time), category)
    TBLPROPERTIES (
        'write.format.default'='parquet',
        'write.parquet.compression-codec'='zstd',
        'write.target-file-size-bytes'='134217728',
        'write.distribution-mode'='hash',
        'write.metadata.delete-after-commit.enabled'='true'
    )
    """)

    logger.info("Table glue_catalog.public_transport.vehicle_positions is ready")


@task
def build_input_path(base_path: str, hours_back: int = 2) -> str:
    """
    Build S3 input path for recent hourly partitions.

    Args:
        base_path: Base S3 path (e.g., s3a://public-transport-dataset/raw)
        hours_back: Number of hours to look back for data

    Returns:
        S3 path pattern for reading data
    """
    logger = get_run_logger()

    now = datetime.utcnow()
    paths = []

    for i in range(hours_back):
        dt = now - timedelta(hours=i)
        path = f"{base_path}/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/hour={dt.hour:02d}/"
        paths.append(path)

    input_path = ",".join(paths)
    logger.info(f"Processing data from paths: {paths}")

    return input_path


@task
def read_and_transform_data(spark: SparkSession, input_path: str):
    """
    Read JSONL from S3 and transform to flat structure.
    """
    logger = get_run_logger()
    logger.info(f"Reading data from: {input_path}")

    try:
        df = spark.read.schema(RAW_SCHEMA).json(input_path)
        record_count = df.count()
        logger.info(f"Read {record_count} records from S3")

        if record_count == 0:
            logger.warning("No records found in input path")
            return None

        flat_df = df.select(
            col("entity_id"),
            col("vehicle.id").alias("vehicle_id"),
            col("vehicle.license_plate").alias("license_plate"),
            col("trip.route_id").alias("route_id"),
            col("trip.trip_id").alias("trip_id"),
            col("trip.start_time").alias("trip_start_time"),
            col("trip.start_date").alias("trip_start_date"),
            col("position.latitude").alias("latitude"),
            col("position.longitude").alias("longitude"),
            col("position.bearing").alias("bearing"),
            col("position.speed").alias("speed"),
            col("vehicle_timestamp"),
            col("feed_timestamp"),
            col("category"),
            col("ingestion_timestamp"),
        ).withColumn(
            "event_time",
            to_timestamp(from_unixtime(col("vehicle_timestamp")))
        )

        logger.info(f"Transformed {flat_df.count()} records")
        return flat_df

    except Exception as e:
        logger.error(f"Error reading data: {e}")
        raise


@task
def write_to_iceberg(spark: SparkSession, df, table_name: str):
    """Write DataFrame to Iceberg table."""
    logger = get_run_logger()

    if df is None:
        logger.info("No data to write, skipping")
        return 0

    record_count = df.count()
    logger.info(f"Writing {record_count} records to {table_name}")

    df.writeTo(table_name).append()

    logger.info(f"Successfully wrote {record_count} records to Iceberg")
    return record_count


@task
def run_table_maintenance(spark: SparkSession):
    """Run Iceberg table maintenance operations"""
    logger = get_run_logger()
    logger.info("Running table maintenance operations")

    spark.sql("""
    CALL glue_catalog.system.rewrite_data_files(
        table => 'public_transport.vehicle_positions',
        strategy => 'binpack',
        options => map('target-file-size-bytes', '134217728')
    )
    """)
    logger.info("File compaction completed")

    spark.sql("""
    CALL glue_catalog.system.expire_snapshots(
        table => 'public_transport.vehicle_positions',
        older_than => TIMESTAMP 'now' - INTERVAL 30 days,
        retain_last => 10
    )
    """)
    logger.info("Snapshot expiration completed")


@task
def stop_spark_session(spark: SparkSession):
    """Stop Spark session"""
    logger = get_run_logger()
    spark.stop()
    logger.info("Spark session stopped")


@flow(name="public-transit-iceberg-ingest")
def transit_iceberg_pipeline(hours_back: int = 2, maintenance: bool = False):
    """
    Main flow for ingesting public transit data to Iceberg.

    Steps:
    1. Create Spark session with Iceberg configuration
    2. Ensure Iceberg table exists
    3. Build input path for recent partitions
    4. Read and transform JSONL data
    5. Write to Iceberg table
    6. Optionally run maintenance operations
    7. Stop Spark session
    """
    logger = get_run_logger()

    # Load configuration
    config_path = Path(__file__).parent / "config.json"
    config_data = get_json_config(config_path)

    s3_base_path = config_data["s3_raw_path"]
    warehouse_path = config_data["s3_warehouse_path"]
    iceberg_table = config_data["iceberg_table"]

    logger.info(f"Starting transit Iceberg ingest pipeline")
    logger.info(f"S3 base path: {s3_base_path}, Hours back: {hours_back}")

    spark = None
    try:
        spark = create_spark_session(warehouse_path)
        ensure_table_exists(spark)

        input_path = build_input_path(s3_base_path, hours_back)
        df = read_and_transform_data(spark, input_path)
        records_written = write_to_iceberg(spark, df, iceberg_table)

        if maintenance:
            run_table_maintenance(spark)

        logger.info(f"Pipeline completed. Records written: {records_written}")
        return records_written

    finally:
        if spark:
            stop_spark_session(spark)


@flow(name="public-transit-iceberg-maintenance")
def transit_maintenance_pipeline():
    """Maintenance flow for Iceberg table optimization."""
    logger = get_run_logger()
    logger.info("Starting Iceberg maintenance pipeline")

    # Load configuration
    config_path = Path(__file__).parent / "config.json"
    config_data = get_json_config(config_path)
    warehouse_path = config_data["s3_warehouse_path"]

    spark = None
    try:
        spark = create_spark_session(warehouse_path)
        run_table_maintenance(spark)
        logger.info("Maintenance pipeline completed")

    finally:
        if spark:
            stop_spark_session(spark)
