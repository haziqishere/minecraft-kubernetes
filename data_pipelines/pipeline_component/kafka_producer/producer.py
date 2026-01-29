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
from google.protobuf.json_format import MessageToDict
import time
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import signal
import sys
from config import (
    API_ENDPOINTS, KAFKA_CONFIG, KAFKA_TOPIC, POLL_INTERVAL, API_TIMEOUT,
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
        # Use MessageToDict for reliable protobuf -> dict conversion
        # preserving_proto_field_name=True keeps snake_case field names
        vehicle_dict = MessageToDict(
            entity.vehicle,
            preserving_proto_field_name=True
        )
        tz = ZoneInfo("Asia/Kuala_Lumpur")

        # Build enriched payload
        return {
            # Original data from protobuf
            'entity_id': entity.id,
            'trip': vehicle_dict.get('trip', {}),
            'position': vehicle_dict.get('position', {}),
            'vehicle': vehicle_dict.get('vehicle', {}),
            'vehicle_timestamp': vehicle_dict.get('timestamp'),

            # Metadata (enrichment at source)
            # feed_timestamp in milliseconds for Kafka Connect partitioning
            'feed_timestamp': feed_timestamp * 1000,
            'category': category,
            'ingestion_timestamp': datetime.now(tz=tz).isoformat(),
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
                KAFKA_TOPIC,
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