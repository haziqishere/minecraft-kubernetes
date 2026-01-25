import os
from pathlib import Path
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, current_timestamp, to_date, from_unixtime
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType, IntegerType

from utilities.config_utils import get_json_config
from utilities.aws_utils import get_sm_client, retrieve_secret

# Load configuration
config_path = Path(__file__).parent / "config.json"
config = get_json_config(config_path)

S3_OUTPUT_PATH = config["S3_OUTPUT_PATH"]
KAFKA_BOOSTRAP_SERVERS = config["KAFKA_BOOSTRAP_SERVERS"]
KAFKA_TOPIC = config["KAFKA_TOPIC"]
KAFKA_SSL_CA = ["KAFKA_SSL_CA"]
KAFKA_SECRETS_NAME = ["KAFKA_SECRETS_NAME"]
CHECKPOINT_LOCATION = f'{S3_OUTPUT_PATH}/checkpoints/transit-streaming'

sm_client = get_sm_client()
KAFKA_SASL_USERNAME = retrieve_secret(
    sm_client,
    KAFKA_SECRETS_NAME,
    config["KAFKA_SASL_USERNAME_KEY"]
)
KAFKA_SASL_PASSWORD = retrieve_secret(
    sm_client,
    KAFKA_SECRETS_NAME,
    config["KAFKA_SASL_PASSWORD_KEY"]
)

# Create Spark session
spark = SparkSession.builder \
    .appName("TransitPositionsStreaming") \
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
    .config("spark.hadoop.fs.s3a.aws.credentials.provider", "com.amazonaws.auth.DefaultAWSCredentialsProviderChain") \
    .getOrCreate()

# Set log level
spark.sparkContext.setLogLevel("WARN")

# Define schema for transit position messages
# Based on GTFS Realtime VehiclePosition format
transit_schema = StructType([
    StructField("vehicle_id", StringType(), True),
    StructField("route_id", StringType(), True),
    StructField("trip_id", StringType(), True),
    StructField("latitude", DoubleType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("bearing", DoubleType(), True),
    StructField("speed", DoubleType(), True),
    StructField("timestamp", LongType(), True),
    StructField("current_stop_sequence", IntegerType(), True),
    StructField("current_status", StringType(), True),
    StructField("category", StringType(), True),
    StructField("ingestion_time", StringType(), True),
])

# Build JAAS config for SASL authentication
jaas_config = f'org.apache.kafka.common.security.scram.ScramLoginModule required username="{KAFKA_SASL_USERNAME}" password="{KAFKA_SASL_PASSWORD}";'

# Read from Kafka with SASL_SSL authentication
df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_BOOSTRAP_SERVERS) \
    .option("subscribe", KAFKA_TOPIC) \
    .option("startingOffsets", "latest") \
    .option("kafka.security.protocol", "SASL_SSL") \
    .option("kafka.sasl.mechanism", "SCRAM-SHA-256") \
    .option("kafka.sasl.jaas.config", jaas_config) \
    .option("kafka.ssl.truststore.type", "PEM") \
    .option("kafka.ssl.truststore.location", KAFKA_SSL_CA) \
    .option("failOnDataLoss", "false") \
    .load()

# Parse JSON messages and add processing metadata
parsed_df = df.select(
    from_json(col("value").cast("string"), transit_schema).alias("data"),
    col("timestamp").alias("kafka_timestamp")
).select(
    "data.*",
    "kafka_timestamp",
    current_timestamp().alias("processing_time")
)

# Add partition column: date derived from timestamp (unix epoch -> date)
partitioned_df = parsed_df \
    .withColumn("date", to_date(from_unixtime(col("timestamp"))))

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