# Layer 1 — Multi-Tenant Kafka Ingest: Build Summary

**Project:** SaaS Behavioral Intelligence Platform  
**Layer:** 1 of 5 — Event Ingest  
**Status:** ✅ Complete — 4,163 messages across 6 partitions, balanced distribution confirmed  

---

## What We Built

A production-grade, multi-tenant event ingestion pipeline that simulates the behavioral event stream of a B2B SaaS platform. Fifty fictional tenant accounts emit clickstream events (page views, feature clicks, API calls, session starts/ends) at rates driven by their plan tier. Events are serialized with Avro, validated against a schema registry, and written to Kafka with a composite partition key.

The output of this layer — a live `saas-events` topic — is the raw input for Layer 2 (Flink session stitching).

---

## Stack

| Component | Technology | Version |
|---|---|---|
| Message broker | Apache Kafka (KRaft mode) | Confluent CP 7.6.1 |
| Schema registry | Confluent Schema Registry | 7.6.1 |
| Serialization | Avro | via `confluent-kafka` |
| Producer | Python | 3.11+ |
| Tenant simulation | Faker + custom profiles | — |
| Local orchestration | Docker Compose | — |
| Observability | Kafka UI | provectuslabs/kafka-ui |

---

## File Structure

```
saas-behavioral-platform/
├── docker-compose.yml              # Kafka + Schema Registry + Kafka UI
├── .env                            # Connection config (not committed)
└── layer1_ingest/
    ├── schemas/
    │   └── saas_event.avsc         # Avro schema — source of truth for event shape
    ├── producer/
    │   ├── config.py               # Kafka client config, constants, event type allowlist
    │   ├── tenant_profiles.py      # 50 tenant definitions with plan-based behavior
    │   └── simulator.py            # Main producer loop
    └── tests/
        └── test_schema.py          # Schema evolution validation
```

---

## Architecture Decisions

### Decision 1 — KRaft over Zookeeper

**Options considered:**
- Zookeeper-based Kafka (legacy, still widely used in tutorials)
- KRaft mode (Kafka's native consensus protocol, GA since Kafka 3.3)

**Choice: KRaft**

Zookeeper is a separate process that Kafka has historically depended on for cluster coordination — leader election, topic metadata, broker registration. KRaft replaces Zookeeper entirely by embedding the Raft consensus protocol directly into Kafka brokers, so one fewer service to run, configure, and monitor.

As of Confluent CP 7.6, Zookeeper mode is deprecated. All new Confluent Cloud deployments are KRaft. Using KRaft locally matches what production systems look like today and removes a common source of local setup failures (Zookeeper startup races).

**Interview answer:** "I used KRaft because Zookeeper is being retired across the Kafka ecosystem. KRaft eliminates a separate coordination service, reduces operational complexity, and is what Confluent Cloud runs natively. There's no reason to build on a deprecated dependency."

---

### Decision 2 — Partition key strategy: composite `tenant_id::user_id`

**Options considered:**

| Strategy | Ordering guarantee | Risk |
|---|---|---|
| Round-robin (no key) | None | Events from same user scattered; session stitching impossible |
| `tenant_id` only | Per-tenant ordering | Enterprise tenants (high volume) create hot partitions |
| `user_id` only | Per-user ordering | No tenant isolation; consumers must filter cross-tenant in-stream |
| `tenant_id::user_id` (composite) | Per-user ordering within tenant | Slightly wider key space, soft tenant isolation |

**Choice: composite key**

Kafka's partitioner hashes the key and maps it to a partition. Same key always lands in the same partition, guaranteeing ordered delivery for that key. By using `tenant_id::user_id` as the key:

- All events for a given user within a given tenant land in the same partition, in order — which Layer 2 (Flink) needs for correct session stitching.
- The key space is proportional to the number of users, not tenants — enterprise tenants with 500 users produce 500 distinct keys, distributing their load rather than hammering one partition.
- Tenant isolation is enforced downstream (in the Flink job and dbt models) rather than at the broker level.

**Proof from screenshot:** Partition message counts — 666 / 610 / 796 / 738 / 594 / 759 — show no hot partition despite enterprise tenants generating 10–50x more events than free-tier tenants.

**Interview answer:** "Partitioning by tenant alone would give me per-tenant ordering but create hot partitions for high-volume accounts — one enterprise tenant could saturate a partition. Partitioning by user alone loses tenant boundaries and forces consumers to do cross-tenant filtering in-stream. The composite key gets me per-user ordering, distributes load proportional to user count, and keeps tenant isolation a downstream concern where it's cheaper to enforce."

---

### Decision 3 — Avro over JSON for serialization

**Options considered:**
- JSON (no schema enforcement, human-readable)
- Avro with Schema Registry (binary, schema-enforced, registry-backed)
- Protobuf (binary, schema-enforced, no native Confluent registry support in this stack)

**Choice: Avro + Schema Registry**

JSON has no enforcement — a producer can send `{"event_type": null}` and the consumer will happily deserialize garbage. In a multi-tenant system where 50 different simulated tenants are producing events, one malformed producer silently corrupts downstream consumers.

Avro solves this in two ways:
1. Binary encoding — smaller message size (no field name repetition per message)
2. Schema Registry handshake — every message includes a 5-byte header (magic byte + schema ID). The consumer fetches the schema by ID, validates against it, and deserializes. A message that doesn't match the schema fails at the producer, not silently downstream.

The schema ID approach means you don't send the full schema with every message — just 4 bytes. At 4,000+ messages, that's meaningful size savings.

**Interview answer:** "Avro gives me schema enforcement at the producer, before bad data enters the pipeline. JSON would let malformed events through silently. The Schema Registry means I can evolve the schema without breaking consumers — new optional fields with null defaults are forward-compatible. I also get binary encoding, which matters at scale."

---

### Decision 4 — `event_type` as string, not Avro enum

**Options considered:**
- Avro `enum` type — fixed set of symbols baked into the schema
- `string` with application-level allowlist validation

**Choice: string with allowlist in `config.py`**

Avro enums are not forward-compatible by default. If a consumer has schema v1 with symbols `{PAGE_VIEW, FEATURE_CLICK, API_CALL}` and receives a message produced with schema v2 that adds `AI_FEATURE_USED`, the v1 consumer throws a deserialization error on the unknown symbol — it has no idea what to do with it.

Using a `string` field means:
- New event types can be added by updating the allowlist in `config.py` — no new schema version required
- Existing consumers continue to work; they may not handle the new type but they don't crash
- Validation is explicit in code and visible to reviewers

This was validated during implementation: adding `AI_FEATURE_USED` to the allowlist mid-run produced no schema registry error and no consumer disruption.

**Interview answer:** "Avro enums break forward compatibility — a consumer on an older schema version will throw on an unknown symbol. In a SaaS product where the event taxonomy evolves constantly, I want to add event types without a coordinated schema migration. Using a string with an enforced allowlist gives me the same safety guarantee at the application layer with none of the schema versioning coordination cost."

---

### Decision 5 — Denormalize `plan_tier` and `session_id` into every event

**Options considered:**
- Normalize: store plan in a separate tenant table, join in stream layer
- Denormalize: include plan and session context in every event payload

**Choice: denormalize**

The Flink job in Layer 2 processes events from a Kafka stream at high throughput. Doing a database lookup mid-stream to find a tenant's current plan would require a remote call per event — adding latency and a failure point that can stall the entire stream.

By including `plan_tier` in every event at emission time, the stream processor is self-contained. It has everything it needs in the message itself.

`session_id` is denormalized for the same reason: Flink's session stitching job groups events into sessions. If session context lived in a separate store, the job would need stateful lookups across a network boundary.

The tradeoff is storage — every event carries a few extra bytes. At this scale, that's negligible compared to the operational simplicity of a self-contained event.

---

## Tenant Simulation Design

50 tenants are built at import time with `random.seed(42)` — the seed makes profiles deterministic across restarts, which matters when Layer 4's ML model is trained on this data. If tenant behavior changed every restart, training data would be inconsistent.

Plan distribution mirrors realistic SaaS economics:

| Plan | Proportion | Events/sec | Silence probability |
|---|---|---|---|
| Free | 40% | 0.05 – 0.3 | 20% |
| Starter | 30% | 0.3 – 1.0 | 10% |
| Growth | 20% | 1.0 – 4.0 | 4% |
| Enterprise | 10% | 4.0 – 15.0 | 1% |

**Silence probability** is the probability a tenant emits zero events on a given tick. Free-tier tenants go silent 20% of the time. This is the behavioral signal Layer 4's churn model will learn to detect — a free-tier tenant that goes silent for 3 days is likely churning.

Each tenant also has weighted feature affinities — `dashboard`, `reports`, `ai_assistant`, etc. — generated randomly but fixed per tenant. This means tenant behavior is realistic and consistent: one tenant is a heavy reports user, another lives in integrations. The ML model can learn these patterns.

---

## What the Screenshot Confirms

From the Kafka UI screenshot taken after the producer ran:

| Metric | Value | What it means |
|---|---|---|
| Total messages | 4,163 | Producer running successfully, no delivery errors |
| Partitions | 6 | Topic created correctly with intended partition count |
| Partition distribution | 594–796 | No hot partition; composite key working as designed |
| Replication factor | 1 | Correct for local single-broker setup |
| Mode | local-kraft | KRaft confirmed, no Zookeeper |
| Schema Registry | visible in sidebar | Registry connected and accessible |

The tightest partition has 594 messages and the busiest has 796 — a spread of ~25%. For 50 tenants with wildly different event rates, that's solid distribution.

---

## What Layer 2 Consumes From Here

The Flink session stitching job (Layer 2) will consume the `saas-events` topic as its source. It will:

1. Read Avro-serialized events using the same Schema Registry
2. Use `tenant_id + user_id` to group events per user
3. Use `session_id` (already in the event) to stitch events into sessions
4. Apply a 30-minute inactivity watermark to close sessions
5. Handle late-arriving events (mobile clients, network lag) via event-time processing

Everything Layer 2 needs — user identity, session context, plan tier, event timestamp — is already in the event payload. No additional lookups required.

---

*Layer 1 complete. Next: Layer 2 — Flink stateful session stitching.*
