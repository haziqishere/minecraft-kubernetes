#!/bin/bash
set -e

echo "Starting Spark dependencies setup for Spark 4.0.1..."

# ===== AWS SDK v2 for Spark 4.0.1 / Hadoop 3.4.1 =====
echo "Setting up AWS SDK v2..."

mkdir -p /usr/share/aws/aws-java-sdk /usr/share/aws/hadoop

# AWS SDK v2 Bundle (required for Spark 4.0.1)
curl -L https://repo1.maven.org/maven2/software/amazon/awssdk/bundle/2.20.160/bundle-2.20.160.jar -o /usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-2.20.160.jar

# AWS SDK v2 S3 Transfer Manager (required for ObjectTransfer class)
curl -L https://repo1.maven.org/maven2/software/amazon/awssdk/s3-transfer-manager/2.20.160/s3-transfer-manager-2.20.160.jar -o /usr/share/aws/aws-java-sdk/s3-transfer-manager-2.20.160.jar

# Hadoop AWS for Hadoop 3.4.1 (matches Spark 4.0.1)
curl -L https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar -o /usr/share/aws/hadoop/hadoop-aws-3.4.1.jar

# ============= KAFKA SETUP =============  
echo "Setting up Kafka connector..."  
  
mkdir -p /usr/share/kafka/  
  
# Download Kafka connector JAR for Spark 4.0.1  
curl -L https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.13/4.0.1/spark-sql-kafka-0-10_2.13-4.0.1.jar \  
    -o /usr/share/kafka/spark-sql-kafka-0-10.jar  
 
# ============= ICEBERG SETUP =============
echo "Setting up Iceberg..."

mkdir -p /usr/share/aws/iceberg/lib/

# Download Iceberg JARs compatible with Spark 3.5 (using compatible versions for Spark 4.0.1)
curl -L https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.13/1.7.1/iceberg-spark-runtime-3.5_2.13-1.7.1.jar \
    -o /usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar

curl -L https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.7.1/iceberg-aws-bundle-1.7.1.jar \
    -o /usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar

# Copy ALL required JAR files to Spark's jars directory
echo "Copying JARs to Spark classpath..."
cp /usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-2.20.160.jar /opt/spark/jars/
cp /usr/share/aws/aws-java-sdk/s3-transfer-manager-2.20.160.jar /opt/spark/jars/
cp /usr/share/aws/hadoop/hadoop-aws-3.4.1.jar /opt/spark/jars/
cp /usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar /opt/spark/jars/
cp /usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar /opt/spark/jars/
cp /usr/share/kafka/spark-sql-kafka-0-10.jar /opt/spark/jars/


# ============= SPARK CONFIGURATION =============
echo "Configuring Spark..."

# Create conf directory if it doesn't exist
mkdir -p /opt/spark/conf/

# Configure Spark defaults
cat >> /opt/spark/conf/spark-defaults.conf <<'EOF'

# Spark mode configuration
spark.submit.deployMode	client
spark.master	local[*]

# Enable Glue Data Catalog
spark.sql.catalogImplementation	hive
spark.hadoop.hive.metastore.client.factory.class	com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory

# S3A Configuration (AWS SDK v2)
spark.hadoop.fs.s3a.impl	org.apache.hadoop.fs.s3a.S3AFileSystem
spark.hadoop.fs.s3a.aws.credentials.provider	org.apache.hadoop.fs.s3a.TemporaryAWSCredentialsProvider
spark.hadoop.fs.s3a.path.style.access	false
spark.hadoop.fs.s3a.connection.ssl.enabled	true

# Memory Configuration
spark.driver.memory	4g
spark.executor.memory	4g
spark.memory.fraction	0.8
spark.memory.storageFraction	0.3

# Parallelism and Partitioning
spark.default.parallelism	100
spark.sql.shuffle.partitions	100
spark.sql.files.maxPartitionBytes	134217728

# Network and Shuffle Optimization
spark.reducer.maxSizeInFlight	96m
spark.shuffle.file.buffer	1m
spark.shuffle.io.maxRetries	10
spark.shuffle.io.retryWait	30s

# S3 Optimization
spark.hadoop.fs.s3a.connection.maximum	100
spark.hadoop.fs.s3a.connection.timeout	300000
spark.hadoop.fs.s3a.threads.max	20
spark.hadoop.fs.s3a.connection.establish.timeout	5000
spark.hadoop.fs.s3a.attempts.maximum	20
spark.hadoop.fs.s3a.socket.send.buffer	8192
spark.hadoop.fs.s3a.socket.recv.buffer	8192

# GC and JVM Tuning
spark.driver.extraJavaOptions	-XX:+UseG1GC -XX:+UnlockDiagnosticVMOptions -XX:+G1SummarizeConcMark -XX:InitiatingHeapOccupancyPercent=35 -XX:ConcGCThreads=4
spark.executor.extraJavaOptions	-XX:+UseG1GC -XX:+UnlockDiagnosticVMOptions -XX:+G1SummarizeConcMark -XX:InitiatingHeapOccupancyPercent=35 -XX:ConcGCThreads=4

# Serialization
spark.serializer	org.apache.spark.serializer.KryoSerializer
spark.kryoserializer.buffer.max	1024m
spark.kryoserializer.buffer	64k

# SQL Join Optimization
spark.sql.autoBroadcastJoinThreshold	30m

# Dynamic allocation
spark.dynamicAllocation.enabled	true
spark.dynamicAllocation.initialExecutors	2
spark.dynamicAllocation.minExecutors	2
spark.dynamicAllocation.maxExecutors	10

# Cleanup strategy
spark.cleaner.periodicGC.interval	30min
spark.cleaner.referenceTracking.cleanCheckpoints	true
EOF

# Create spark-env.sh with ALL required JARs
cat > /opt/spark/conf/spark-env.sh <<'EOF'
#!/bin/bash

export SPARK_CLASSPATH=$SPARK_CLASSPATH:/usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-2.20.160.jar:/usr/share/aws/aws-java-sdk/s3-transfer-manager-2.20.160.jar:/usr/share/aws/hadoop/hadoop-aws-3.4.1.jar:/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar:/usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar
EOF

chmod +x /opt/spark/conf/spark-env.sh

echo "Spark dependencies setup completed successfully!"
