import os
from dotenv import load_dotenv

load_dotenv()

KAFKA_CONFIG = {
    "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
    "client.id": "saas-event-producer",
    # Batch up to 16KB before flushing — better throughput
    "batch.size": 16384,
    # Wait 5ms for more messages before sending a batch
    "linger.ms": 5,
    "retries": 3,
    "retry.backoff.ms": 100,
}

SCHEMA_REGISTRY_CONFIG = {
    "url": os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081"),
}

TOPIC = os.getenv("KAFKA_TOPIC", "saas-events")
NUM_PARTITIONS = 6

# Allowlist — enforced here since event_type is a string not enum
#VALID_EVENT_TYPES = {
#    "PAGE_VIEW", "FEATURE_CLICK", "API_CALL",
#    "SESSION_START", "SESSION_END",
#}

VALID_EVENT_TYPES = {
    "PAGE_VIEW", "FEATURE_CLICK", "API_CALL",
    "SESSION_START", "SESSION_END",
    "AI_FEATURE_USED",    # ← new
}

PRODUCT_FEATURES = [
    "dashboard", "reports", "exports", "integrations",
    "ai_assistant", "user_management", "billing", "api_keys",
]
