# 7. Server architecture: queued ingest, materialised documents, incident lifecycle

Date: 2026-10-24 · Status: accepted

## Context

Step 3 turns the engine into a service: model servers send predictions and, later, labels; the
dashboard reads per-model and per-incident documents. The forces:

- **Ingest must not hurt the model server.** It is on the request path of someone else's
  service. Slow or failing monitoring must cost the caller nothing but missing data.
- **Analysis is expensive and windowed.** A day's document needs every prediction of that day
  (and, for the label check, the six before it). Doing that per request, or per insert, is
  wasteful; doing it on read makes the dashboard slow.
- **Labels arrive late, out of order, and sometimes before the prediction they belong to.**
- **The static demo and the live service must not disagree.** The hosted demo is computed in
  memory; a live deployment goes through HTTP, Redis and Postgres. Divergence would be invisible
  until someone compared them.

## Decisions

**Ingest is queued.** The API validates a batch (schema, known model, known features, sane
timestamps), fills in defaults, appends it to a Redis Stream and answers `202 Accepted`. A
worker in a consumer group writes it to Postgres. Delivery is at-least-once: an entry is
acknowledged only after its transaction commits. Writes are idempotent (predictions keyed on
model, request id and timestamp; labels upserted), so redelivery is harmless. Unacknowledged
entries are reclaimed from a crashed worker after a minute; an entry that fails five times, or
can't be decoded, goes to a dead-letter stream with the reason. Acknowledged entries are trimmed,
so the stream's length is the backlog, and the API answers `503` with `Retry-After` once the
backlog passes a limit. A database outage therefore pushes back on clients instead of growing
Redis without bound, and the SDK backs off.

*Alternatives.* Writing to Postgres directly from the API couples ingest latency to database
latency and makes a migration or vacuum visible to every model server. Kafka gives the same
semantics with far more to operate; Redis Streams is enough below hundreds of thousands of
events a second and is often already deployed. The cost is one more component, and Redis must
persist the stream (append-only file, `everysec`): a Redis crash can lose up to a second of
accepted batches.

**Predictions are partitioned by UTC day.** Partitions are created by the worker before its
first insert into a day, under an advisory lock, and dropped whole after retention (90 days by
default), which is far cheaper than `DELETE`. There is no default partition: a row for a missing
partition fails loudly instead of being parked where it would block creating that partition
later. Features are stored as `jsonb`. That is the scaling limit of this design: at tens of
millions of predictions a day, a columnar store (ClickHouse, Parquet on object storage) is the
next step, behind the same `load_days` interface.

**Documents are materialised.** Every write marks the affected (version, day) pairs dirty: a
prediction's own day and, because the label check pools a rolling week, the six days after it up
to today. The worker claims dirty days with `SKIP LOCKED` (so several workers share the load),
waits two seconds for a burst to settle, recomputes those days and then rebuilds the model page,
the overview row and the incident. Claim, compute and write share one transaction: a crash
loses nothing, and a day marked dirty again mid-computation is computed again afterwards. Reads
are a primary-key lookup. A day's document is only as fresh as the last recompute, a few seconds
behind ingest.

**One analysis package, used twice.** `sentinel_server.analysis` (pure functions over data
frames) produces every document. The worker calls it on data loaded from Postgres; the demo
builder calls it on data in memory. A parity test pushes two demo scenarios through the real
path (CSV upload, HTTP ingest, Redis, worker, Postgres, read API) and requires the result to
equal the in-memory documents exactly. Running the simulator against a full local stack produced
documents identical to the committed demo for all four models and three incidents.

**Incidents follow alerting practice.** An incident opens when a rule holds for two consecutive
days and resolves after seven consecutive days on which no rule holds, dated from the first quiet
day. Seven is the label check's window: a quiet week means every label it pools post-dates the
problem. Resolving on the first quiet day was the obvious alternative and the first version did
it. On credit-risk, labels for the newest days had not arrived yet, so the label check went quiet
while the drift continued, and the incident closed and would have reopened. An episode that
ended more than a week before anyone looked (a backfill) opens no incident. One open incident per
model is enforced by a partial unique index.

**API keys are 256-bit random secrets stored as SHA-256 digests**, with scopes `ingest`, `read`
and `admin`. A slow password hash protects guessable secrets; these aren't guessable, and a fast
digest keeps authentication to one indexed lookup. Read endpoints can be made public for a demo
dashboard. Errors are RFC 9457 problem details.

## Measured

On one machine (API: one uvicorn process; one worker; Postgres 16 and Redis local):

| | |
| --- | --- |
| SDK `log_prediction` | about 11 µs per call, including generating the features |
| SDK → API, accepted | about 20–29k predictions/s |
| Worker, written to Postgres | about 22k predictions/s, including process start-up |
| Recompute after a 100k-prediction burst | about 5 s, including the 2 s debounce |
| Demo (182,624 predictions, 95,541 labels) | live documents identical to the static demo |

## Consequences

- Ingest has three moving parts (API, Redis, worker) instead of one. Each scales out
  independently: more API processes behind a load balancer, more workers in the consumer group.
- Writes are visible to reads only after the worker has written and recomputed: seconds, not
  milliseconds. The `202` says so.
- Incidents resolve a week after a problem stops. For a model with a short label delay that is
  conservative; the constant lives in one place if a per-model setting is needed.
- A version's reference CSV is kept in Postgres so monitors can be refitted after an engine
  upgrade; the upload limit (64 MB) bounds it.
