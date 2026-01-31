#!/bin/bash
set -e

echo "Starting Spark dependencies setup for Spark 3.5.7..."

# ===== AWS SDK v1 for Spark 3.5.7 / Hadoop 3.3.6 =====
echo "Setting up AWS SDK v1..."

mkdir -p /usr/share/aws/aws-java-sdk /usr/share/aws/hadoop

# AWS SDK v1 Bundle (required for Hadoop 3.3.6)
curl -L https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.367/aws-java-sdk-bundle-1.12.367.jar -o /usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-1.12.367.jar

# Hadoop AWS for Hadoop 3.3.6 (matches Spark 3.5.7)
curl -L https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.6/hadoop-aws-3.3.6.jar -o /usr/share/aws/hadoop/hadoop-aws-3.3.6.jar

# ============= KAFKA SETUP =============
echo "Setting up Kafka connector..."

mkdir -p /usr/share/kafka/

# Download Kafka connector JAR for Spark 3.5.7 (Scala 2.12) and its dependencies
curl -L https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.7/spark-sql-kafka-0-10_2.12-3.5.7.jar -o /usr/share/kafka/spark-sql-kafka-0-10.jar
curl -L https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.7/spark-token-provider-kafka-0-10_2.12-3.5.7.jar -o /usr/share/kafka/spark-token-provider-kafka-0-10.jar
curl -L https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar -o /usr/share/kafka/kafka-clients.jar
curl -L https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar -o /usr/share/kafka/commons-pool2.jar
curl -L https://repo1.maven.org/maven2/org/lz4/lz4-java/1.8.0/lz4-java-1.8.0.jar -o /usr/share/kafka/lz4-java.jar
curl -L https://repo1.maven.org/maven2/org/xerial/snappy/snappy-java/1.1.10.5/snappy-java-1.1.10.5.jar -o /usr/share/kafka/snappy-java.jar

# ============= ICEBERG SETUP =============
echo "Setting up Iceberg..."

mkdir -p /usr/share/aws/iceberg/lib/

# Download Iceberg JARs compatible with Spark 3.5 (Scala 2.12)
curl -L https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.7.1/iceberg-spark-runtime-3.5_2.12-1.7.1.jar \
    -o /usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar

curl -L https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.7.1/iceberg-aws-bundle-1.7.1.jar \
    -o /usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar

# Copy ALL required JAR files to Spark's jars directory
echo "Copying JARs to Spark classpath..."
cp /usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-1.12.367.jar /opt/spark/jars/
cp /usr/share/aws/hadoop/hadoop-aws-3.3.6.jar /opt/spark/jars/
cp /usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar /opt/spark/jars/
cp /usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar /opt/spark/jars/
cp /usr/share/kafka/*.jar /opt/spark/jars/


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

# S3A Configuration (AWS SDK v1)
spark.hadoop.fs.s3a.impl	org.apache.hadoop.fs.s3a.S3AFileSystem
spark.hadoop.fs.s3a.aws.credentials.provider	org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider,com.amazonaws.auth.EnvironmentVariableCredentialsProvider
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

export SPARK_CLASSPATH=$SPARK_CLASSPATH:/usr/share/aws/aws-java-sdk/aws-java-sdk-bundle-1.12.367.jar:/usr/share/aws/hadoop/hadoop-aws-3.3.6.jar:/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar:/usr/share/aws/iceberg/lib/iceberg-aws-bundle.jar:/usr/share/kafka/*
EOF

chmod +x /opt/spark/conf/spark-env.sh

echo "Spark dependencies setup completed successfully!"
