# Production Capacity Protocol v1 (Draft)

This protocol measures a specific deployed system with real PostgreSQL, S3,
OpenAI, and Langfuse dependencies. It is separate from the network-free Load
and Capacity v1-v3 protocols. Results apply only to the recorded deployment,
provider quotas, workload, and test window; they are not a universal production
SLO.

The protocol remains **draft** until its workload, thresholds, deployment
identity, and three repeated runs have been reviewed and frozen.

## Isolation boundary

The preferred target is a separate production-equivalent deployment. It must
use the same application image and reviewed runtime configuration as
production, while using a different API hostname, PostgreSQL instance (not
only a different schema on a shared capacity-limited instance), S3 bucket,
OpenAI project key, Langfuse environment/project, and synthetic data set. Keep
the endpoint off the normal user route and restrict network access to the test
operator or load generator.

`compose.production-capacity.local.yaml` is provided only to rehearse this
separation. Its dedicated Compose project, database volume, and port prevent
accidental writes to the normal local stack, but local Docker is not a
production-equivalent capacity target.

## What the runner automates

`evals.run_production_capacity`:

- schedules `ramp`, `steady`, `spike`, and `soak` stages using an open arrival
  rate expressed as jobs per minute;
- bounds total requests, in-flight requests, duration, reserved cost, and
  measured cost;
- stops dispatch when stage errors or sampled CPU, memory, or PostgreSQL
  connection utilization exceed configured limits;
- validates API completion, database readback, S3 output retrieval, Langfuse
  trace completeness, trace privacy, model identity, and measured cost;
- scans run-correlated records for missing, duplicate, or pending state;
- uses scoped `s3:ListBucket` access to detect output objects created during
  the isolated test window without a corresponding database record;
- writes privacy-safe JSON and Markdown artifacts under `evals/results/`.

Artifacts never contain prompts, S3 object keys, signed URLs, credentials,
generation IDs, or raw Langfuse trace IDs.

## Required manual confirmations

Before a paid run, a human must verify:

1. the target is an approved isolated production-equivalent environment, or an
   explicitly approved production canary window;
2. its instance count, Uvicorn worker count, PostgreSQL tier and pool, region,
   deployed commit, OpenAI models, and provider quotas are recorded;
3. synthetic records and S3 outputs cannot affect real users and may be safely
   cleaned up;
4. the cost cap, request cap, duration, arrival rates, and resource thresholds
   are approved;
5. dashboards and alerts are visible to an operator who can stop the test;
6. the S3 identity has `HeadObject` for the reference image and scoped
   `ListBucket` for the `generations/` prefix;
7. the metrics endpoint described below returns current production resource
   data.

The CLI requires three explicit confirmations for every paid run:

```text
--confirm-cloud-spend
--confirm-production-capacity-test
--confirm-isolated-test-data
```

They are assertions, not substitutes for the review above.

## Metrics endpoint contract

The runner polls `--metrics-url` every five seconds by default. The endpoint
must return only these numeric fields:

```json
{
  "cpu_percent": 42.5,
  "memory_percent": 61.0,
  "database_active_connections": 18,
  "database_max_connections": 100
}
```

For a remote target the URL must use HTTPS. If it needs authorization, place
the complete header value in `PRODUCTION_CAPACITY_METRICS_AUTHORIZATION`; the
value is never written to results. The runner rejects malformed metrics and
marks the overall production-capacity gate false when metrics are absent.

The application includes a disabled-by-default protected endpoint at
`/internal/capacity-metrics`. It is suitable for a single container and must be
restricted at the network layer as well as by its authorization value. For a
multi-replica deployment, point `--metrics-url` at an authenticated aggregate
exporter backed by the platform monitoring system; sampling a random replica
through the public load balancer is not sufficient.

`--allow-missing-resource-metrics` exists only for runner integration testing.
Results produced with it are not eligible for a production-capacity claim.

## Authentication and privacy

If the API requires authentication, set the complete authorization header in
an environment variable rather than on the command line:

```bash
export PRODUCTION_CAPACITY_AUTHORIZATION='Bearer ...'
```

Do not commit either authorization variable, the reference object key, or raw
result directories. A unique token is appended to each synthetic prompt so the
runner can find missing, duplicate, failed, or pending database rows. The token
and prompt are used in memory only and are not written to evaluation artifacts.

## Free preflight

The preflight makes no OpenAI model call. It checks API/database health,
history access, S3 reference-object access, scoped S3 listing, Langfuse
authentication, the workload, the pessimistic cost reservation, and resource
metrics.

```bash
export LIVE_SMOKE_REFERENCE_OBJECT_KEY='uploads/your-existing-reference.png'

python -m evals.run_production_capacity \
  --api-base-url https://api.example.com \
  --expected-api-host api.example.com \
  --target-environment-label production-canary \
  --metrics-url https://metrics.example.com/capacity-snapshot \
  --validate-only
```

Expected output includes `paid_model_calls: 0`, a bounded reserved cost, and
successful checks for S3 listing and resource metrics.

## Paid pilot

Run a four-request pilot before any larger test:

```bash
python -m evals.run_production_capacity \
  --api-base-url https://api.example.com \
  --expected-api-host api.example.com \
  --target-environment-label production-canary \
  --metrics-url https://metrics.example.com/capacity-snapshot \
  --stage ramp:0.5-1:2 \
  --stage steady:1:2 \
  --maximum-request-count 4 \
  --maximum-cost-usd 0.50 \
  --maximum-reserved-cost-per-request-usd 0.10 \
  --maximum-in-flight 2 \
  --maximum-duration-seconds 900 \
  --confirm-cloud-spend \
  --confirm-production-capacity-test \
  --confirm-isolated-test-data \
  --fail-on-gate
```

The pessimistic reservation must fit within the total cost cap before the
runner dispatches anything. If one request costs more than its reservation,
the runner records the violation and stops before the next stage. A provider
can still charge more than an estimate already authorized; provider-side
budgets and quotas remain the final hard spending boundary.

## Candidate capacity run

The default draft schedule contains 24 requests:

```text
ramp:0.5-1:4
steady:1:6
spike:2:4
soak:1:10
```

It is deliberately conservative and is not automatically the correct workload
for a real deployment. Review the observed production traffic mix and provider
quota before changing rates. Keep the protocol hard limits at or below 50
requests, 10 in flight, two hours, and `$10` until a new reviewed protocol is
created.

## Acceptance and interpretation

A candidate result requires:

- all planned requests dispatched and the configured success-rate gate met;
- one terminal database record per request, with no missing, duplicate, or
  pending records;
- every successful S3 output retrievable and zero orphan outputs;
- complete privacy-safe Langfuse traces and measured costs;
- correct frozen model identities;
- observed cost below the cap;
- CPU, memory, and PostgreSQL connection utilization below reviewed limits;
- no automatic stop condition.

Repeat the same candidate test at least three times. Then run a longer soak at
the proposed safe arrival rate. The defensible capacity is the highest repeated
arrival rate that satisfies every gate for the exact recorded deployment. Do
not generalize it to a different worker count, database tier, model, region,
quota, or traffic mix.

