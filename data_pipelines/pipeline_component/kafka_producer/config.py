import os
from pathlib import Path

from utilities.config_utils import get_json_config
from utilities.aws_utils import get_sm_client, retrieve_secret

# Load configuration from config.json
config_path = Path(__file__).parent / "config.json"
config = get_json_config(config_path)

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

# Retrieve SASL credentials from AWS Secrets Manager
sm_client = get_sm_client(credentials=None)
KAFKA_SASL_USERNAME = retrieve_secret(
    sm_client,
    config["KAFKA_SECRET_NAME"],
    config["KAFKA_SASL_USERNAME_KEY"]
)
KAFKA_SASL_PASSWORD = retrieve_secret(
    sm_client,
    config["KAFKA_SECRET_NAME"],
    config["KAFKA_SASL_PASSWORD_KEY"]
)

# Kafka topic (used separately, not in producer config)
KAFKA_TOPIC = config["KAFKA_TOPIC"]

# Kafka Producer Configuration with Aiven SASL + SSL
KAFKA_CONFIG = {
    'bootstrap_servers': config["KAFKA_BOOTSTRAP_SERVERS"].split(','),
    'acks': 'all',
    'retries': 3,
    'compression_type': 'lz4',
    'batch_size': 16384,
    'linger_ms': 10,
    # Aiven SASL + SSL Authentication
    'security_protocol': 'SASL_SSL',
    'sasl_mechanism': 'SCRAM-SHA-256',
    'sasl_plain_username': KAFKA_SASL_USERNAME,
    'sasl_plain_password': KAFKA_SASL_PASSWORD,
    'ssl_cafile': config["KAFKA_SSL_CA"],
}

# Producer Configuration
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '5'))  # seconds
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '10'))  # seconds
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv('CIRCUIT_BREAKER_THRESHOLD', '5'))
CIRCUIT_BREAKER_TIMEOUT = int(os.getenv('CIRCUIT_BREAKER_TIMEOUT', '60'))  # seconds

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')