import os
from pathlib import Path
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, current_timestamp, to_date, from_unixtime
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType

from utilities.config_utils import get_json_config
from utilities.aws_utils import get_sm_client, retrieve_secret

# Load configuration
config_path = Path(__file__).parent / "config.json"
config = get_json_config(config_path)

S3_OUTPUT_PATH = config["S3_OUTPUT_PATH"]
KAFKA_BOOTSTRAP_SERVERS = config["KAFKA_BOOTSTRAP_SERVERS"]
KAFKA_TOPIC = config["KAFKA_TOPIC"]
KAFKA_SSL_CA = config["KAFKA_SSL_CA"]
KAFKA_SECRET_NAME = config["KAFKA_SECRET_NAME"]
CHECKPOINT_LOCATION = f'{S3_OUTPUT_PATH}/checkpoints/transit-streaming'

sm_client = get_sm_client()
KAFKA_SASL_USERNAME = retrieve_secret(
    sm_client,
    KAFKA_SECRET_NAME,
    config["KAFKA_SASL_USERNAME_KEY"]
)
KAFKA_SASL_PASSWORD = retrieve_secret(
    sm_client,
    KAFKA_SECRET_NAME,
    config["KAFKA_SASL_PASSWORD_KEY"]
)

# Create Spark session with S3A configuration for Hadoop 3.4.x / AWS SDK v2
spark = SparkSession.builder \
    .appName("TransitPositionsStreaming") \
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
    .config("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider") \
    .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID", "")) \
    .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY", "")) \
    .config("spark.hadoop.fs.s3a.endpoint", "s3.amazonaws.com") \
    .getOrCreate()

# Set log level
spark.sparkContext.setLogLevel("WARN")

# Define schema for transit position messages
# Matches the nested JSON structure from Kafka producer
trip_schema = StructType([
    StructField("trip_id", StringType(), True),
    StructField("start_time", StringType(), True),
    StructField("start_date", StringType(), True),
    StructField("route_id", StringType(), True),
])

position_schema = StructType([
    StructField("latitude", DoubleType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("bearing", DoubleType(), True),
    StructField("speed", DoubleType(), True),
])

vehicle_schema = StructType([
    StructField("id", StringType(), True),
    StructField("license_plate", StringType(), True),
])

transit_schema = StructType([
    StructField("entity_id", StringType(), True),
    StructField("trip", trip_schema, True),
    StructField("position", position_schema, True),
    StructField("vehicle", vehicle_schema, True),
    StructField("vehicle_timestamp", LongType(), True),
    StructField("feed_timestamp", LongType(), True),
    StructField("category", StringType(), True),
    StructField("ingestion_timestamp", StringType(), True),
    StructField("producer_version", StringType(), True),
])

# SSL cert paths (mounted from Kubernetes secret)
KAFKA_SSL_CERT_PATH = "/etc/kafka/certs/service.cert"
KAFKA_SSL_KEY_PATH = "/etc/kafka/certs/service.key"

# Read cert and key contents for Kafka SSL config
with open(KAFKA_SSL_CERT_PATH, 'r') as f:
    KAFKA_SSL_CERT = f.read()
with open(KAFKA_SSL_KEY_PATH, 'r') as f:
    KAFKA_SSL_KEY = f.read()

# Read from Kafka with SSL (mTLS) authentication
df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS) \
    .option("subscribe", KAFKA_TOPIC) \
    .option("startingOffsets", "latest") \
    .option("kafka.security.protocol", "SSL") \
    .option("kafka.ssl.truststore.type", "PEM") \
    .option("kafka.ssl.truststore.location", KAFKA_SSL_CA) \
    .option("kafka.ssl.keystore.type", "PEM") \
    .option("kafka.ssl.keystore.certificate.chain", KAFKA_SSL_CERT) \
    .option("kafka.ssl.keystore.key", KAFKA_SSL_KEY) \
    .option("failOnDataLoss", "false") \
    .load()

# Parse JSON messages and add processing metadata
parsed_df = df.select(
    from_json(col("value").cast("string"), transit_schema).alias("data"),
    col("timestamp").alias("kafka_timestamp")
).select(
    # Flatten nested structure
    col("data.entity_id"),
    col("data.trip.trip_id").alias("trip_id"),
    col("data.trip.route_id").alias("route_id"),
    col("data.trip.start_time").alias("trip_start_time"),
    col("data.trip.start_date").alias("trip_start_date"),
    col("data.position.latitude").alias("latitude"),
    col("data.position.longitude").alias("longitude"),
    col("data.position.bearing").alias("bearing"),
    col("data.position.speed").alias("speed"),
    col("data.vehicle.id").alias("vehicle_id"),
    col("data.vehicle.license_plate").alias("license_plate"),
    col("data.vehicle_timestamp").alias("vehicle_timestamp"),
    col("data.feed_timestamp"),
    col("data.category"),
    col("data.ingestion_timestamp"),
    col("data.producer_version"),
    col("kafka_timestamp"),
    current_timestamp().alias("processing_time")
)

# Add partition column: date derived from vehicle_timestamp (unix epoch -> date)
partitioned_df = parsed_df \
    .withColumn("date", to_date(from_unixtime(col("vehicle_timestamp"))))

# Write to S3 as Parquet with partitioning by date and route_id
query = partitioned_df.writeStream \
    .format("parquet") \
    .outputMode("append") \
    .option("path", f"{S3_OUTPUT_PATH}/transit-positions") \
    .option("checkpointLocation", CHECKPOINT_LOCATION) \
    .partitionBy("date", "route_id") \
    .trigger(processingTime="10 seconds") \
    .start()

print(f"Streaming started: Reading from {KAFKA_TOPIC}, writing to {S3_OUTPUT_PATH}/transit-positions")
query.awaitTermination()