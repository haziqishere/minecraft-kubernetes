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