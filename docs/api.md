# Sentinel API

Base path `/v1`. JSON in and out. The running server also serves an OpenAPI description at
`/openapi.json` and interactive docs at `/docs`.

## Authentication

Send an API key as `Authorization: Bearer snl_…`. Keys carry scopes:

| Scope | Allows |
| --- | --- |
| `ingest` | `POST /v1/ingest/*` |
| `read` | every `GET` |
| `admin` | everything, including the registry |

Create keys with `sentinel-admin create-key --name <name> --scope <scope>`; the secret is printed
once. Revoke with `sentinel-admin revoke-key <prefix>`. With `SENTINEL_PUBLIC_READ=true`, reads
need no key (for a demo dashboard); writes always do.

## Registry

| | |
| --- | --- |
| `PUT /v1/registry/models/{id}` | Register a model or update its details: `name`, `team`, `description`, `label_delay_days`. `201` when created. Ids are lowercase slugs. |
| `POST /v1/registry/models/{id}/versions` | Upload a version's reference data (multipart, below). `202`: validated now, fitted in the background. |
| `GET /v1/registry/models/{id}/versions/{version}` | The version's `status`: `pending`, `ready` or `failed` (with `error`). |
| `POST /v1/registry/models/{id}/versions/{version}/activate` | Make a fitted version the default for ingest and the one the dashboard shows. |
| `GET /v1/registry/models`, `GET /v1/registry/models/{id}` | Models with their versions. |

The reference upload is a CSV with one row per scored request from a period you trust: the
feature columns, the model's positive-class probability and the true outcome. Form fields:

| Field | Default | |
| --- | --- | --- |
| `version` | required | Immutable; upload a new version to change it. |
| `reference` | required | The CSV file, up to 64 MB. 20–50k rows is plenty. |
| `score_column` | `score` | Probabilities in [0, 1]. |
| `label_column` | `label` | 0 or 1; both must occur. |
| `prediction_column` | none | The decision taken; otherwise `score >= decision_threshold`. |
| `decision_threshold` | `0.5` | |
| `activate` | `true` | Make it the active version once fitted. |

Every other column is a feature. Feature kinds (numeric or categorical) are inferred from the
file and fixed for the version.

## Ingest

Both endpoints answer `202 Accepted` with `{"accepted": n, "queued_as": "<stream id>"}`: the
batch is durable and will be written, usually within a second, and appears in reads a few
seconds after that. Up to 500 records per request. Retrying a batch is safe; duplicates are
ignored.

`POST /v1/ingest/predictions`

```json
{
  "model_id": "credit-risk",
  "version": "v3",
  "predictions": [
    {
      "request_id": "loan-8812",
      "ts": "2026-10-24T09:31:02Z",
      "features": {"monthly_income": 48000, "utilization": 0.41, "division": "Khulna", "channel": "branch"},
      "score": 0.82,
      "prediction": 1,
      "latency_ms": 31.5
    }
  ]
}
```

`version` defaults to the active version, `ts` to the time of receipt (no zone means UTC),
`prediction` to `score >= decision_threshold`; `latency_ms` is optional. Features not in the
version's schema are rejected; missing ones are treated as null. Timestamps may not be in the
future or older than the retention period (90 days).

`POST /v1/ingest/labels`

```json
{"model_id": "credit-risk", "labels": [{"request_id": "loan-8812", "label": 1}]}
```

Labels may arrive before or after their prediction. A later label for the same request replaces
the earlier one.

The [Python SDK](../sdk/python/README.md) batches, retries and backs off for you.

## Documents

What the dashboard reads; the shapes are defined in [`web/src/data/schema.ts`](../web/src/data/schema.ts).

| | |
| --- | --- |
| `GET /v1/fleet` | Every model's overview row and every open incident. |
| `GET /v1/models/{id}` | The model page: thirty days of estimated and measured metrics, per-feature drift, reference facts. `404` until the model has a fitted active version and traffic. |
| `GET /v1/incidents?status=open\|resolved\|all&model_id=…` | Incidents, newest first. |
| `GET /v1/incidents/{id}` | One incident: the signals, the decomposition of the drop, ranked segments, example rows, traffic shifts. |

## Health

`GET /healthz` answers when the process is serving; `GET /readyz` when Postgres and Redis also
answer (`503` otherwise).

## Errors

Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details with content type
`application/problem+json`:

```json
{
  "type": "https://github.com/SifatSwapnil2022/Sentinel-AI/blob/main/docs/api.md#invalid-records",
  "title": "Invalid records",
  "status": 422,
  "detail": "2 problem(s) in the batch; nothing was queued.",
  "errors": [{"index": 3, "message": "unknown feature(s): colour"}]
}
```

### unauthenticated

`401`. No key, a malformed key, or a revoked one.

### forbidden

`403`. The key lacks the scope this endpoint needs.

### invalid-request

`422`. The body doesn't match the schema. `errors` lists each field with its `location` and a
`message`.

### invalid-records

`422`. The batch is well formed, but some records aren't acceptable: unknown features, or
timestamps in the future or past retention. `errors` gives each record's `index`. Nothing in
the batch was queued.

### invalid-reference

`422`. The reference upload was rejected. `problems` lists every issue found.

### batch-too-large

`413`. More than 500 records in one request.

### body-too-large

`413`. The request body exceeds the size limit (8 MB; 64 MB for reference uploads).

### reference-too-large

`413`. The reference file exceeds 64 MB.

### unknown-model

`404`. No model with this id is registered.

### unknown-version

`404`. The model has no version with this name.

### no-active-version

`409`. Ingest without a `version`, for a model whose first version isn't fitted yet. Wait for
the version to be `ready`, or name it explicitly.

### version-failed

`409`. The named version failed to fit; its status has the reason.

### version-exists

`409`. Versions are immutable; upload under a new name.

### version-not-ready

`409`. Only a fitted version can be activated.

### no-model-data

`404`. The model has no computed documents yet.

### unknown-incident

`404`. No incident with this id.

### not-found

`404`. No such endpoint.

### method-not-allowed

`405`. The endpoint exists but not with this method.

### backpressure

`503`, with `Retry-After`. Too many batches are waiting to be written. Retry after the given
number of seconds; the SDK does.

### internal

`500`. An unexpected error. It is logged with details; the response carries none.

### http-error

Any other HTTP error status.
