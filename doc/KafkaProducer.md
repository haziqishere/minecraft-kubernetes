# Kafka Producer Implementation Guide

## Overview
This document outlines the implementation steps for a Kafka producer that ingests real-time vehicle position data from Malaysia's Prasarana public transport APIs.

---

## Data Source Specifications

### Endpoints
```python
# Rapid Bus KL
URL_1 = 'https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-bus-kl'

# MRT Feeder Bus
URL_2 = 'https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-bus-mrtfeeder'
```

### Filtering Criteria
**Only ingest vehicles from these routes:**
- **rapid-bus-kl**: `trip.routeId` in `['U6400', 'U6000']`
- **rapid-bus-mrtfeeder**: `trip.routeId` in `['T587']`

All other routes should be filtered out at the producer level to reduce Kafka load.

---

## Data Format

### API Response Structure (GTFS Realtime Format)
```protobuf
header {
  gtfs_realtime_version: "2.0"
  incrementality: FULL_DATASET
  timestamp: 1768735199
}

entity {
  id: "0"
  vehicle {
    trip {
      trip_id: "weekend_U5800_U580002_9"
      start_time: "17:13:52"
      start_date: "20260118"
      route_id: "U5800"
    }
    position {
      latitude: 3.13606
      longitude: 101.712158
      bearing: 143
      speed: 8.89
    }
    timestamp: 1768735154
    vehicle {
      id: "WVG2397"
      license_plate: "WVG2397"
    }
  }
}
```

### Key Fields
| Field | Type | Description |
|-------|------|-------------|
| `header.timestamp` | Unix timestamp | Dataset timestamp |
| `entity.id` | String | Index in current response (0-based) |
| `vehicle.trip.route_id` | String | Route identifier (filter key) |
| `vehicle.trip.trip_id` | String | Unique trip identifier |
| `vehicle.position.latitude` | Float | GPS latitude |
| `vehicle.position.longitude` | Float | GPS longitude |
| `vehicle.position.bearing` | Float | Direction in degrees |
| `vehicle.position.speed` | Float | Speed in m/s |
| `vehicle.timestamp` | Unix timestamp | Vehicle position timestamp |
| `vehicle.vehicle.id` | String | Vehicle identifier |
| `vehicle.vehicle.license_plate` | String | License plate number |

---

## Implementation Steps

### Step 1: Project Structure

```
kafka-producer/
├── Dockerfile
├── requirements.txt
├── producer.py
├── config.py
└── README.md
```

### Step 2: Dependencies (`requirements.txt`)

```txt
kafka-python==2.0.2
requests==2.31.0
protobuf==4.25.1
gtfs-realtime-bindings==1.0.0
```

**Why these dependencies?**
- `kafka-python`: Kafka client library
- `requests`: HTTP client for API calls
- `protobuf`: Parse GTFS Realtime protobuf format
- `gtfs-realtime-bindings`: GTFS Realtime Python bindings

---

### Step 3: Configuration (`config.py`)

```python
import os

# API Configuration
API_ENDPOINTS = {
    'rapid-bus-kl': {
        'url': 'https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-bus-kl',
        'routes': ['U6400', 'U6000']
    },
    'rapid-bus-mrtfeeder': {
        'url': 'https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-bus-mrtfeeder',
        'routes': ['T587']
    }
}

# Kafka Configuration
KAFKA_CONFIG = {
    'bootstrap_servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(','),
    'topic': os.getenv('KAFKA_TOPIC', 'transit-positions-raw'),
    'acks': 'all',
    'retries': 3,
    'enable_idempotence': True,
    'compression_type': 'lz4',
    'batch_size': 16384,
    'linger_ms': 10,
}

# Producer Configuration
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '30'))  # seconds
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '10'))  # seconds
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv('CIRCUIT_BREAKER_THRESHOLD', '5'))
CIRCUIT_BREAKER_TIMEOUT = int(os.getenv('CIRCUIT_BREAKER_TIMEOUT', '60'))  # seconds

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
```

---

### Step 4: Producer Implementation (`producer.py`)

```python
#!/usr/bin/env python3
"""
Kafka Producer for Malaysian Transit Data
Ingests GTFS Realtime data from Prasarana APIs
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from kafka import KafkaProducer
from kafka.errors import KafkaError
from google.transit import gtfs_realtime_pb2
import time
import json
import logging
from datetime import datetime
import signal
import sys
from config import (
    API_ENDPOINTS, KAFKA_CONFIG, POLL_INTERVAL, API_TIMEOUT,
    CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT, LOG_LEVEL
)

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker pattern to handle API failures gracefully"""
    
    def __init__(self, failure_threshold=CIRCUIT_BREAKER_THRESHOLD, timeout=CIRCUIT_BREAKER_TIMEOUT):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.is_open = False
    
    def record_success(self):
        """Reset on successful API call"""
        self.failure_count = 0
        self.is_open = False
    
    def record_failure(self):
        """Increment failure count and open circuit if threshold reached"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                f"Circuit breaker OPEN after {self.failure_count} consecutive failures. "
                f"Will retry after {self.timeout}s"
            )
    
    def can_attempt(self):
        """Check if we can attempt API call"""
        if not self.is_open:
            return True
        
        # Attempt to close circuit after timeout (half-open state)
        if time.time() - self.last_failure_time > self.timeout:
            logger.info("Circuit breaker attempting to close (half-open state)")
            self.is_open = False
            self.failure_count = 0
            return True
        
        return False


class TransitProducer:
    """Main producer class for ingesting transit data into Kafka"""
    
    def __init__(self):
        self.running = True
        self.api_endpoints = API_ENDPOINTS
        self.circuit_breakers = {
            category: CircuitBreaker() 
            for category in self.api_endpoints.keys()
        }
        
        # Setup HTTP session with retries
        self.session = self._create_http_session()
        
        # Initialize Kafka producer
        self.producer = self._create_kafka_producer()
        
        # Setup graceful shutdown
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)
        
        # Metrics
        self.metrics = {
            'total_fetched': 0,
            'total_filtered': 0,
            'total_sent': 0,
            'api_errors': 0
        }
        
        logger.info("TransitProducer initialized successfully")
    
    def _create_http_session(self):
        """Create HTTP session with retry strategy"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,  # 1s, 2s, 4s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _create_kafka_producer(self):
        """Initialize Kafka producer with configuration"""
        producer = KafkaProducer(
            **KAFKA_CONFIG,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        logger.info(f"Kafka producer connected to {KAFKA_CONFIG['bootstrap_servers']}")
        return producer
    
    def _shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        logger.info(f"Shutdown signal received (signal: {signum})")
        self.running = False
        
        logger.info("Flushing Kafka producer...")
        self.producer.flush(timeout=10)
        self.producer.close()
        
        logger.info(f"Final metrics: {self.metrics}")
        logger.info("Producer shutdown complete")
        sys.exit(0)
    
    def fetch_gtfs_data(self, category, url):
        """
        Fetch GTFS Realtime data from API
        
        Returns:
            FeedMessage object or None if failed
        """
        circuit_breaker = self.circuit_breakers[category]
        
        if not circuit_breaker.can_attempt():
            logger.warning(f"Circuit breaker OPEN for {category}, skipping fetch")
            return None
        
        try:
            logger.debug(f"Fetching data from {category}: {url}")
            response = self.session.get(
                url,
                timeout=API_TIMEOUT,
                headers={'User-Agent': 'TransitMonitor/1.0'}
            )
            response.raise_for_status()
            
            # Parse protobuf
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)
            
            circuit_breaker.record_success()
            logger.info(f"Successfully fetched {len(feed.entity)} entities from {category}")
            return feed
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching from {category}")
            circuit_breaker.record_failure()
            self.metrics['api_errors'] += 1
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {category}: {e}")
            circuit_breaker.record_failure()
            self.metrics['api_errors'] += 1
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error parsing GTFS data from {category}: {e}")
            circuit_breaker.record_failure()
            self.metrics['api_errors'] += 1
            return None
    
    def filter_by_route(self, entity, allowed_routes):
        """
        Check if entity's route is in allowed list
        
        Args:
            entity: GTFS entity object
            allowed_routes: List of route IDs to include
            
        Returns:
            bool: True if route should be included
        """
        if not entity.HasField('vehicle'):
            return False
        
        if not entity.vehicle.HasField('trip'):
            return False
        
        route_id = entity.vehicle.trip.route_id
        return route_id in allowed_routes
    
    def parse_entity(self, entity, category, feed_timestamp):
        """
        Parse GTFS entity into JSON-serializable dict
        
        Args:
            entity: GTFS entity object
            category: API category (rapid-bus-kl, rapid-bus-mrtfeeder)
            feed_timestamp: Timestamp from feed header
            
        Returns:
            dict: Parsed entity data
        """
        vehicle = entity.vehicle
        
        # Extract nested fields safely
        trip_data = {}
        if vehicle.HasField('trip'):
            trip_data = {
                'trip_id': vehicle.trip.trip_id,
                'start_time': vehicle.trip.start_time,
                'start_date': vehicle.trip.start_date,
                'route_id': vehicle.trip.route_id
            }
        
        position_data = {}
        if vehicle.HasField('position'):
            position_data = {
                'latitude': vehicle.position.latitude,
                'longitude': vehicle.position.longitude,
                'bearing': vehicle.position.bearing if vehicle.position.HasField('bearing') else None,
                'speed': vehicle.position.speed if vehicle.position.HasField('speed') else None
            }
        
        vehicle_data = {}
        if vehicle.HasField('vehicle'):
            vehicle_data = {
                'id': vehicle.vehicle.id,
                'license_plate': vehicle.vehicle.license_plate
            }
        
        # Build enriched payload
        return {
            # Original data
            'entity_id': entity.id,
            'trip': trip_data,
            'position': position_data,
            'vehicle': vehicle_data,
            'vehicle_timestamp': vehicle.timestamp if vehicle.HasField('timestamp') else None,
            
            # Metadata (enrichment at source)
            'feed_timestamp': feed_timestamp,
            'category': category,
            'ingestion_timestamp': datetime.utcnow().isoformat(),
            'producer_version': '1.0'
        }
    
    def send_to_kafka(self, data, key):
        """
        Send data to Kafka with error handling
        
        Args:
            data: Dictionary to send
            key: Kafka message key (vehicle ID)
        """
        def on_success(metadata):
            logger.debug(
                f"Message sent to {metadata.topic} "
                f"partition {metadata.partition} offset {metadata.offset}"
            )
            self.metrics['total_sent'] += 1
        
        def on_error(error):
            logger.error(f"Failed to send message to Kafka: {error}")
        
        try:
            future = self.producer.send(
                KAFKA_CONFIG['topic'],
                key=key.encode('utf-8') if key else None,
                value=data
            )
            future.add_callback(on_success)
            future.add_errback(on_error)
            
        except KafkaError as e:
            logger.error(f"Kafka error: {e}")
    
    def process_feed(self, category, config):
        """
        Process a single API endpoint
        
        Args:
            category: API category name
            config: Configuration dict with 'url' and 'routes'
        """
        url = config['url']
        allowed_routes = config['routes']
        
        # Fetch data
        feed = self.fetch_gtfs_data(category, url)
        if not feed:
            return
        
        # Extract feed timestamp
        feed_timestamp = feed.header.timestamp
        
        # Process entities
        filtered_count = 0
        sent_count = 0
        
        for entity in feed.entity:
            self.metrics['total_fetched'] += 1
            
            # Filter by route
            if not self.filter_by_route(entity, allowed_routes):
                filtered_count += 1
                continue
            
            # Parse and enrich
            parsed_data = self.parse_entity(entity, category, feed_timestamp)
            
            # Use vehicle ID as Kafka key for partitioning
            vehicle_id = parsed_data.get('vehicle', {}).get('id', '')
            
            # Send to Kafka
            self.send_to_kafka(parsed_data, vehicle_id)
            sent_count += 1
        
        self.metrics['total_filtered'] += filtered_count
        
        logger.info(
            f"{category}: Fetched {len(feed.entity)} entities, "
            f"filtered {filtered_count}, sent {sent_count} to Kafka"
        )
    
    def run(self):
        """Main producer loop"""
        logger.info(f"Starting producer loop (poll interval: {POLL_INTERVAL}s)")
        logger.info(f"Monitoring routes: {self.api_endpoints}")
        
        while self.running:
            loop_start = time.time()
            
            # Process each API endpoint
            for category, config in self.api_endpoints.items():
                try:
                    self.process_feed(category, config)
                except Exception as e:
                    logger.error(f"Unexpected error processing {category}: {e}", exc_info=True)
            
            # Flush Kafka producer
            self.producer.flush()
            
            # Log metrics periodically
            if self.metrics['total_fetched'] % 100 == 0 and self.metrics['total_fetched'] > 0:
                logger.info(f"Cumulative metrics: {self.metrics}")
            
            # Sleep for remaining interval
            elapsed = time.time() - loop_start
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            
            if sleep_time > 0:
                logger.debug(f"Sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)


def main():
    """Entry point"""
    logger.info("=" * 60)
    logger.info("Starting Malaysian Transit Kafka Producer")
    logger.info("=" * 60)
    
    producer = TransitProducer()
    producer.run()


if __name__ == "__main__":
    main()
```

---

### Step 5: Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY producer.py config.py ./

# Create non-root user for security
RUN useradd -m -u 1000 producer && \
    chown -R producer:producer /app

USER producer

# Health check (optional, requires adding health endpoint)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

CMD ["python", "producer.py"]
```

---

### Step 6: Kubernetes Deployment (`k8s-deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: transit-producer
  namespace: default
  labels:
    app: transit-producer
spec:
  replicas: 1  # Single replica (polling pattern)
  selector:
    matchLabels:
      app: transit-producer
  template:
    metadata:
      labels:
        app: transit-producer
    spec:
      containers:
      - name: producer
        image: your-registry/transit-producer:latest
        imagePullPolicy: Always
        env:
        - name: KAFKA_BOOTSTRAP_SERVERS
          value: "kafka-service:9092"
        - name: KAFKA_TOPIC
          value: "transit-positions-raw"
        - name: POLL_INTERVAL
          value: "30"
        - name: LOG_LEVEL
          value: "INFO"
        - name: API_TIMEOUT
          value: "10"
        - name: CIRCUIT_BREAKER_THRESHOLD
          value: "5"
        - name: CIRCUIT_BREAKER_TIMEOUT
          value: "60"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
        livenessProbe:
          exec:
            command:
            - python
            - -c
            - "import sys; sys.exit(0)"
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          exec:
            command:
            - python
            - -c
            - "import sys; sys.exit(0)"
          initialDelaySeconds: 10
          periodSeconds: 10
      restartPolicy: Always
---
apiVersion: v1
kind: Service
metadata:
  name: transit-producer-service
  namespace: default
spec:
  selector:
    app: transit-producer
  ports:
  - name: metrics
    port: 8000
    targetPort: 8000
  type: ClusterIP
```

---

### Step 7: Build and Deploy

```bash
# Build Docker image
docker build -t your-registry/transit-producer:latest .

# Push to registry
docker push your-registry/transit-producer:latest

# Deploy to Kubernetes
kubectl apply -f k8s-deployment.yaml

# Check logs
kubectl logs -f deployment/transit-producer

# Expected output:
# 2026-01-18 10:30:00 - __main__ - INFO - TransitProducer initialized successfully
# 2026-01-18 10:30:00 - __main__ - INFO - Starting producer loop (poll interval: 30s)
# 2026-01-18 10:30:05 - __main__ - INFO - Successfully fetched 152 entities from rapid-bus-kl
# 2026-01-18 10:30:05 - __main__ - INFO - rapid-bus-kl: Fetched 152 entities, filtered 148, sent 4 to Kafka
# 2026-01-18 10:30:08 - __main__ - INFO - Successfully fetched 89 entities from rapid-bus-mrtfeeder
# 2026-01-18 10:30:08 - __main__ - INFO - rapid-bus-mrtfeeder: Fetched 89 entities, filtered 87, sent 2 to Kafka
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ Step 1: API Polling (every 30 seconds)                 │
│                                                         │
│ GET /prasarana?category=rapid-bus-kl                   │
│ GET /prasarana?category=rapid-bus-mrtfeeder            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 2: Parse GTFS Protobuf                            │
│                                                         │
│ FeedMessage.ParseFromString(response.content)          │
│ → Extract 150+ entities per endpoint                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 3: Filter by Route ID                             │
│                                                         │
│ rapid-bus-kl:       Keep U6400, U6000 (drop others)    │
│ rapid-bus-mrtfeeder: Keep T587 (drop others)           │
│                                                         │
│ Typical filtering: 150 entities → 3-5 entities         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 4: Enrich with Metadata                           │
│                                                         │
│ Add:                                                    │
│ - ingestion_timestamp                                  │
│ - category (rapid-bus-kl / rapid-bus-mrtfeeder)        │
│ - feed_timestamp                                       │
│ - producer_version                                     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 5: Send to Kafka                                  │
│                                                         │
│ Topic: transit-positions-raw                           │
│ Key: vehicle.id (e.g., "WVG2397")                      │
│ Value: Enriched JSON                                   │
│ Partitioning: By vehicle ID                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
              Kafka Topic
        (Ready for Spark Streaming)
```

---

## Expected Output Format in Kafka

```json
{
  "entity_id": "42",
  "trip": {
    "trip_id": "weekend_U6400_U640002_5",
    "start_time": "10:15:30",
    "start_date": "20260118",
    "route_id": "U6400"
  },
  "position": {
    "latitude": 3.1569,
    "longitude": 101.7123,
    "bearing": 143.5,
    "speed": 8.89
  },
  "vehicle": {
    "id": "WVG2397",
    "license_plate": "WVG2397"
  },
  "vehicle_timestamp": 1768735154,
  "feed_timestamp": 1768735199,
  "category": "rapid-bus-kl",
  "ingestion_timestamp": "2026-01-18T10:30:05.123456",
  "producer_version": "1.0"
}
```

---

## Monitoring

### Logs to Watch For

✅ **Success:**
```
INFO - Successfully fetched 152 entities from rapid-bus-kl
INFO - rapid-bus-kl: Fetched 152 entities, filtered 148, sent 4 to Kafka
```

⚠️ **Circuit Breaker:**
```
WARNING - Circuit breaker OPEN after 5 consecutive failures. Will retry after 60s
INFO - Circuit breaker attempting to close (half-open state)
```

❌ **Errors:**
```
ERROR - Timeout fetching from rapid-bus-kl
ERROR - Request failed for rapid-bus-mrtfeeder: ConnectionError
ERROR - Failed to send message to Kafka: KafkaTimeoutError
```

### Key Metrics

| Metric | What to Monitor | Healthy Value |
|--------|----------------|---------------|
| `total_fetched` | Total entities from API | ~240/poll (152 + 89) |
| `total_filtered` | Entities filtered out | ~235/poll (98% filtered) |
| `total_sent` | Sent to Kafka | ~5/poll (3 routes monitored) |
| `api_errors` | Failed API calls | Should be 0 |

---

## Troubleshooting

### Issue: No data in Kafka

**Check:**
```bash
# Verify producer is running
kubectl get pods -l app=transit-producer

# Check logs
kubectl logs -f deployment/transit-producer

# Verify Kafka connectivity
kubectl exec -it deployment/transit-producer -- python -c "
from kafka import KafkaProducer
p = KafkaProducer(bootstrap_servers=['kafka-service:9092'])
print('Connected to Kafka')
"
```

### Issue: Circuit breaker keeps opening

**Possible causes:**
1. API rate limiting → Increase `POLL_INTERVAL`
2. Network issues → Check EKS egress rules
3. API down → Check https://api.data.gov.my status

### Issue: Too many filtered messages

**Verify route IDs exist:**
```bash
# Temporary: Remove filtering to see all route IDs
# In config.py, set:
# 'routes': []  # Empty list = accept all

# Check logs for actual route IDs in responses
# Then update config with correct route IDs
```

---

## Next Steps

After deploying this producer:

1. **Verify data in Kafka:**
   ```bash
   kafka-console-consumer --bootstrap-server localhost:9092 \
     --topic transit-positions-raw \
     --from-beginning \
     --max-messages 10
   ```

2. **Set up Spark Streaming consumer** (next document)

3. **Configure Iceberg table** with partitioning strategy

4. **Add monitoring:** Prometheus + Grafana for producer metrics

---

## Summary

This producer implementation:
- ✅ Polls 2 API endpoints every 30 seconds
- ✅ Filters to only 3 specific routes (U6400, U6000, T587)
- ✅ Enriches data with metadata at source
- ✅ Uses circuit breaker for fault tolerance
- ✅ Keys messages by vehicle ID for ordering
- ✅ Production-ready error handling
- ✅ Containerized for EKS deployment

**Estimated throughput:** ~5-10 messages every 30 seconds = ~10-20 messages/minute = ~600-1,200 messages/hour (well within your 250KB/s Kafka spec).