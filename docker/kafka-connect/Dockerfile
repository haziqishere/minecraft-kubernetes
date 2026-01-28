FROM confluentinc/cp-kafka-connect:7.6.0

# Install S3 connector from Confluent Hub
RUN confluent-hub install --no-prompt confluentinc/kafka-connect-s3:10.5.7

# Create directory for SSL certificates
USER root
RUN mkdir -p /etc/kafka/certs && chown -R appuser:appuser /etc/kafka/certs
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8083/connectors || exit 1
