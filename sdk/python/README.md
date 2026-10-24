# sentinel-sdk

Send predictions and labels from a model server to Sentinel without slowing the server down.

```python
from sentinel_sdk import Sentinel

sentinel = Sentinel(
    "https://sentinel.example.com",
    api_key=os.environ["SENTINEL_API_KEY"],  # a key with the ingest scope
    model_id="credit-risk",
)

# in the request handler, after scoring
sentinel.log_prediction(
    request_id,
    features,  # dict of feature name -> value
    score=probability,  # positive-class probability, 0 to 1
    latency_ms=elapsed_ms,  # optional
)

# whenever the true outcome is known, possibly weeks later
sentinel.log_label(request_id, defaulted)  # 0 or 1
```

## Guarantees

| | |
|---|---|
| **Never blocks** | `log_*` appends to a memory buffer and returns: a few microseconds, no I/O. A background thread sends batches of up to 500 records. |
| **Never raises** | Invalid input (a score outside 0–1, an unserialisable feature) is logged and counted in `stats.invalid`, not raised into your handler. |
| **Bounded memory** | Each buffer holds `max_buffer` records (100,000 by default). If Sentinel is unreachable long enough to fill it, the oldest records are dropped and counted in `stats.dropped`. |
| **Retries what can succeed** | Network errors, 429 and 5xx are retried with exponential backoff and jitter, honouring `Retry-After`. A batch rejected as invalid (other 4xx) is not retried; it is counted in `stats.rejected`. |
| **At-least-once, deduplicated** | A retried batch may arrive twice; the server keys predictions on request id and timestamp, so duplicates are ignored. |

## Lifecycle

`flush(timeout)` waits until everything buffered has been sent. `close()` flushes for up to five seconds and stops the thread; it also runs at interpreter exit. The client works as a context manager.

With a pre-forking server (gunicorn `--preload`, uWSGI), create the client **after** the fork, in each worker (for gunicorn, in a `post_fork` hook): a thread started before forking doesn't exist in the children.

## Watching for gaps

`sentinel.stats` holds counters since start: `sent`, `dropped`, `rejected`, `failed`, `invalid` and `last_error`. Export them to your metrics system. A rising `dropped` or `failed` means Sentinel is seeing less traffic than you serve.
