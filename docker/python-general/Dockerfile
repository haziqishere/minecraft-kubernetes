FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for data pipelines and kubectl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY docker/python-general/requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Copy data pipelines code
COPY data_pipelines /app/data_pipelines

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH="/app/data_pipelines:${PYTHONPATH}"

# Keep WORKDIR at /app so Prefect entrypoint paths match (data_pipelines/flow/...)
WORKDIR /app

# Default command (can be overridden by Prefect deployments)
CMD ["python"]
