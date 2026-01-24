FROM hazieqishere/python-general:latest

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Create non-root user for security
RUN useradd -m -u 1000 producer && \
    chown -R data_pipelines/kafka_producer/producer:producer /app

USER producer

# Health check (optional, requires adding health endpoint)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

CMD ["python", "producer.py"]