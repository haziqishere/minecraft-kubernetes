from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col
from pyspark.sql.types import StructType, StringType

# Create Spark session
spark = SparkSession.builder \
    .appName("KafkaStreaming") \
    .getOrCreate()

# Define schema
schema = StructType() \
    .add("key", StringType()) \
    .add("value", StringType())

# Read from Kafka
df = spark.readStream \
    .format("kafka") \
    .option("kafka.boostrap.servers","kafka-my-rapidkl-student-298a.c.aivencloud.com:13066") \
    .option("subscribe", "transit-positions") \
    .option("startingOffsets", "latest") \
    .load()

# Parse JSON messages
parsed_df = df.select(
    from_json(col("value").cast("string"), schema).alias("data")
).select("data.*")



# TODO: Enable below when Iceberg Table has been setup
# # Write to your sink (Iceberg Table)
# query = parsed_df.writeStream \
#     .format("iceberg") \
#     .outputMode("append") \
#     .trigger(Trigger.ProcessingTime(1, TimeUnit.MINUTES)) \
#     .option("fanout-enabled", "true") \
#     .option("checkpointLocation", checkpointPath) \
#     .toTable("database.table_name")