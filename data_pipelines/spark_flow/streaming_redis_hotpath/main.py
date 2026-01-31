"""
Spark Structured Streaming: Kafka -> Redis Hot Path

This streaming job reads transit position data from Kafka, preprocesses
the data (fixing timestamp issues), and writes to Redis for real-time
bus tracking applications.

Redis Key Pattern: bus:{route_id}:{license_plate}
TTL: 5 minutes (auto-cleanup for inactive buses)
"""

from pathlib import Path
from datetime import datetime
import redis
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import (
    from_json, col, current_timestamp,
    from_unixtime, date_format
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, LongType
)

from utilities.config_utils import get_json_config
from utilities.aws_utils import get_sm_client, retrieve_secret

# Load configuration
config_path = Path(__file__).parent / "config.json"
config = get_json_config(config_path)

KAFKA_BOOTSTRAP_SERVERS = config["KAFKA_BOOTSTRAP_SERVERS"]
KAFKA_TOPIC = config["KAFKA_TOPIC"]
KAFKA_SSL_CA = config["KAFKA_SSL_CA"]
KAFKA_SECRET_NAME = config["KAFKA_SECRET_NAME"]

REDIS_HOST = config["REDIS_HOST"]
REDIS_PORT = config["REDIS_PORT"]
REDIS_TTL_SECONDS = config["REDIS_TTL_SECONDS"]
PROCESSING_INTERVAL = config["PROCESSING_INTERVAL_SECONDS"]
TIMEZONE = config["TIMEZONE"]

# Retrieve Kafka secrets
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

# SSL cert paths (mounted from Kubernetes secret)
KAFKA_SSL_CERT_PATH = "/etc/kafka/certs/service.cert"
KAFKA_SSL_KEY_PATH = "/etc/kafka/certs/service.key"


def create_spark_session() -> SparkSession:
    """Create Spark session with minimal configuration for streaming."""
    return SparkSession.builder \
        .appName("TransitRedisHotPath") \
        .config("spark.streaming.stopGracefullyOnShutdown", "true") \
        .config("spark.sql.session.timeZone", TIMEZONE) \
        .getOrCreate()


def get_kafka_schema() -> StructType:
    """Define schema for transit position messages from Kafka."""
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

    return StructType([
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


def write_to_redis(batch_df: DataFrame, batch_id: int):
    """
    Write batch data to Redis using HSET with TTL.

    Key pattern: bus:{route_id}:{license_plate}

    This function runs on the driver, collecting data from executors.
    For high throughput, consider using Redis Cluster with partition-aware writes.
    """
    if batch_df.isEmpty():
        print(f"Batch {batch_id}: No data to write")
        return

    # Collect data to driver (for moderate data volumes this is acceptable)
    rows = batch_df.collect()

    # Create Redis connection
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True
    )

    # Use pipeline for batch writes (much faster than individual commands)
    pipe = redis_client.pipeline()

    bus_count = 0
    for row in rows:
        route_id = row['route_id'] or 'unknown'
        license_plate = row['license_plate'] or row['vehicle_id'] or 'unknown'

        # Composite key: bus:{route_id}:{license_plate}
        redis_key = f"bus:{route_id}:{license_plate}"

        # Prepare hash fields
        bus_data = {
            'license_plate': license_plate,
            'route_id': route_id,
            'latitude': str(row['latitude']) if row['latitude'] else '0',
            'longitude': str(row['longitude']) if row['longitude'] else '0',
            'bearing': str(row['bearing']) if row['bearing'] else '0',
            'speed': str(row['speed']) if row['speed'] else '0',
            'category': row['category'] or 'bus',
            'vehicle_id': row['vehicle_id'] or '',
            'trip_id': row['trip_id'] or '',
            'feed_timestamp': str(row['feed_timestamp_corrected']) if row['feed_timestamp_corrected'] else '',
            'feed_timestamp_myt': row['feed_timestamp_myt'] or '',
            'last_updated': str(int(datetime.now().timestamp()))
        }

        # HSET to store bus data
        pipe.hset(redis_key, mapping=bus_data)
        # Set TTL (5 minutes) - auto-cleanup for inactive buses
        pipe.expire(redis_key, REDIS_TTL_SECONDS)

        # Also maintain route index for quick lookups
        route_index_key = f"route:{route_id}:buses"
        pipe.sadd(route_index_key, license_plate)
        pipe.expire(route_index_key, REDIS_TTL_SECONDS)

        bus_count += 1

    # Execute all commands in one round trip
    pipe.execute()

    redis_client.close()

    print(f"Batch {batch_id}: Wrote {bus_count} bus positions to Redis")


def main():
    """Main entry point for the streaming job."""
    print("Starting Kafka -> Redis Hot Path Streaming Job")
    print(f"Kafka: {KAFKA_BOOTSTRAP_SERVERS} / Topic: {KAFKA_TOPIC}")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"Processing interval: {PROCESSING_INTERVAL}")

    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    # Read SSL cert/key contents
    with open(KAFKA_SSL_CERT_PATH, 'r') as f:
        kafka_ssl_cert = f.read()
    with open(KAFKA_SSL_KEY_PATH, 'r') as f:
        kafka_ssl_key = f.read()

    # Read from Kafka with SSL (mTLS) authentication
    raw_df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS) \
        .option("subscribe", KAFKA_TOPIC) \
        .option("startingOffsets", "latest") \
        .option("kafka.security.protocol", "SSL") \
        .option("kafka.ssl.truststore.type", "PEM") \
        .option("kafka.ssl.truststore.location", KAFKA_SSL_CA) \
        .option("kafka.ssl.keystore.type", "PEM") \
        .option("kafka.ssl.keystore.certificate.chain", kafka_ssl_cert) \
        .option("kafka.ssl.keystore.key", kafka_ssl_key) \
        .option("failOnDataLoss", "false") \
        .load()

    transit_schema = get_kafka_schema()

    # Parse JSON and preprocess data
    parsed_df = raw_df.select(
        from_json(col("value").cast("string"), transit_schema).alias("data"),
        col("timestamp").alias("kafka_timestamp")
    ).select(
        # Flatten nested structure
        col("data.entity_id"),
        col("data.trip.trip_id").alias("trip_id"),
        col("data.trip.route_id").alias("route_id"),
        col("data.position.latitude").alias("latitude"),
        col("data.position.longitude").alias("longitude"),
        col("data.position.bearing").alias("bearing"),
        col("data.position.speed").alias("speed"),
        col("data.vehicle.id").alias("vehicle_id"),
        col("data.vehicle.license_plate").alias("license_plate"),
        col("data.vehicle_timestamp").alias("vehicle_timestamp"),
        col("data.feed_timestamp").alias("feed_timestamp_raw"),
        col("data.category"),
        col("kafka_timestamp"),
        current_timestamp().alias("processing_time")
    )

    # Fix feed_timestamp: divide by 1000 (ms -> seconds)
    # The raw value like 1769896778000 is in milliseconds
    # Dividing by 1000 gives 1769896778 which is a valid Unix timestamp
    processed_df = parsed_df \
        .withColumn(
            "feed_timestamp_corrected",
            (col("feed_timestamp_raw") / 1000).cast("long")
        ) \
        .withColumn(
            "feed_timestamp_myt",
            date_format(
                from_unixtime(col("feed_timestamp_corrected")),
                "yyyy-MM-dd HH:mm:ss"
            )
        )

    # Select final columns for Redis
    final_df = processed_df.select(
        "entity_id",
        "trip_id",
        "route_id",
        "latitude",
        "longitude",
        "bearing",
        "speed",
        "vehicle_id",
        "license_plate",
        "category",
        "feed_timestamp_corrected",
        "feed_timestamp_myt",
        "processing_time"
    )

    # Write to Redis using foreachBatch
    query = final_df.writeStream \
        .foreachBatch(write_to_redis) \
        .outputMode("update") \
        .trigger(processingTime=PROCESSING_INTERVAL) \
        .start()

    print(f"Streaming started: {KAFKA_TOPIC} -> Redis")
    print("Press Ctrl+C to stop")

    query.awaitTermination()


if __name__ == "__main__":
    main()
