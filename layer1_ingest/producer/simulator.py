"""
Layer 1 Producer — SaaS Behavioral Event Simulator

Run:
    python -m layer1_ingest.producer.simulator
"""

import uuid, time, random, signal, sys, pathlib
from datetime import datetime, timezone

from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

from .config import KAFKA_CONFIG, SCHEMA_REGISTRY_CONFIG, TOPIC, VALID_EVENT_TYPES
from .tenant_profiles import TENANTS, is_tenant_silent, pick_user, pick_feature

def load_schema_str() -> str:
    path = pathlib.Path(__file__).parent.parent / "schemas" / "saas_event.avsc"
    return path.read_text()

def build_event(tenant_id: str, user_id: str, session_id: str) -> dict:

#    event_type = random.choices(
#        list(VALID_EVENT_TYPES),
#        weights=[0.45, 0.25, 0.15, 0.08, 0.07],
#        k=1
#    )[0]
#
    event_types = list(VALID_EVENT_TYPES)

    weights = {
        "PAGE_VIEW": 0.35,
        "FEATURE_CLICK": 0.25,
        "API_CALL": 0.15,
        "SESSION_START": 0.1,
        "SESSION_END": 0.1,
        "AI_FEATURE_USED": 0.05,
    }
    
    event_type = random.choices(
        event_types,
        weights=[weights[e] for e in event_types]
    )[0]

    return {
        "event_id":     str(uuid.uuid4()),
        "tenant_id":    tenant_id,
        "user_id":      user_id,
        "event_type":   event_type,
        "feature_name": pick_feature(tenant_id) if event_type == "FEATURE_CLICK" else None,
        "timestamp_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "plan_tier":    TENANTS[tenant_id]["plan"],
        "session_id":   session_id,
        "properties": {
            "user_agent": random.choice([
                "Mozilla/5.0 Chrome/120", "Mozilla/5.0 Firefox/121",
                "Mozilla/5.0 Safari/17", "okhttp/4.9.3",
            ]),
            "country": random.choice(["US","GB","DE","IN","BR","CA"]),
        },
    }

def make_partition_key(tenant_id: str, user_id: str) -> bytes:
    return f"{tenant_id}::{user_id}".encode("utf-8")

_delivered = 0

def on_delivery(err, msg):
    global _delivered
    if err:
        print(f"[ERROR] {err}", flush=True)
    else:
        _delivered += 1
        if _delivered % 100 == 0:
            print(f"[OK] {_delivered} delivered | partition={msg.partition()} offset={msg.offset()}", flush=True)

def run():
    schema_str = load_schema_str()
    sr_client  = SchemaRegistryClient(SCHEMA_REGISTRY_CONFIG)
    serializer = AvroSerializer(sr_client, schema_str)
    producer   = Producer(KAFKA_CONFIG)

    def _shutdown(sig, frame):
        print("\nFlushing...", flush=True)
        producer.flush(timeout=10)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)

    print(f"Producer started → topic '{TOPIC}' | {len(TENANTS)} tenants")
    print("Kafka UI: http://localhost:8080")

    session_map: dict[str, tuple[str, int]] = {}

    while True:
        for tenant_id in TENANTS:
            if is_tenant_silent(tenant_id):
                continue
            user_id  = pick_user(tenant_id)
            user_key = f"{tenant_id}::{user_id}"

            if user_key not in session_map or session_map[user_key][1] <= 0:
                session_map[user_key] = (str(uuid.uuid4())[:8], random.randint(5, 15))
            session_id, remaining = session_map[user_key]
            session_map[user_key] = (session_id, remaining - 1)

            event = build_event(tenant_id, user_id, session_id)
            producer.produce(
                topic=TOPIC,
                key=make_partition_key(tenant_id, user_id),
                value=serializer(event, SerializationContext(TOPIC, MessageField.VALUE)),
                on_delivery=on_delivery,
            )

        producer.poll(0)   # triggers delivery callbacks — required
        time.sleep(0.1)

if __name__ == "__main__":
    run()
