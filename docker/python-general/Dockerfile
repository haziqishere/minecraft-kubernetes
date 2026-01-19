FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for data pipelines
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Default command (can be overridden by Prefect deployments)
CMD ["python"]
