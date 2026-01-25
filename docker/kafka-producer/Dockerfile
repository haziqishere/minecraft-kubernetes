FROM haziqishere/python-general:latest

# Install Kafka producer dependencies
COPY docker/kafka-producer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create directory for Kafka SSL certificates (mounted at runtime)
RUN mkdir -p /etc/kafka/certs

# Set PYTHONPATH so utilities can be imported from nested directory
ENV PYTHONPATH="/app/data_pipelines:${PYTHONPATH}"

# Set working directory to kafka_producer (data_pipelines already exists from base image)
WORKDIR /app/data_pipelines/pipeline_component/kafka_producer

# Health check
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

CMD ["python", "producer.py"]