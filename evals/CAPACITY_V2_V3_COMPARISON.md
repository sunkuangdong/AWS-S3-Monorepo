# Capacity v2/v3 Comparison

## Outcome

Capacity v3 increased only the isolated evaluation service's SQLAlchemy pool
from `5 + 10` to `20 + 20`. Across three repeated runs, this moved reproducible
formal request failures above concurrency 96 while improving concurrency-96
median throughput and tail latency. It did not eliminate the performance knee:
96 remained the first saturation candidate in every v3 run.

## Controlled change

| Setting | Frozen v2 | Frozen v3 |
| --- | ---: | ---: |
| SQLAlchemy pool size | 5 | 20 |
| Maximum overflow | 10 | 20 |
| Pool timeout | 30 s | 30 s |
| Uvicorn workers | 1 | 1 |
| Image stub latency | 250 ms | 250 ms |
| PostgreSQL | Real local service | Real local service |
| Cloud calls and cost | 0 / $0 | 0 / $0 |

Business logic, provider delay, worker count, workload, timeout, and safety
rules were unchanged. This bounds the comparison to connection-pool capacity;
it does not prove the pool was the only source of queueing.

## Repeated results

| Metric | Capacity v2 median | Capacity v3 median | Change |
| --- | ---: | ---: | ---: |
| C64 throughput | 165.910 RPS | 165.947 RPS | +0.0% |
| C64 P95 | 804.597 ms | 897.125 ms | +11.5% |
| C96 throughput | 70.147 RPS | 80.569 RPS | +14.9% |
| C96 P95 | 4,352.453 ms | 3,375.503 ms | -22.4% |
| C96 fully successful runs | 1/3 | 3/3 | +2 runs |

Each version used three runs. V3 completed 3,000/3,000 measured requests at
both concurrency 64 and 96 with matching database state. At concurrency 128,
v3 completed 2,993/3,000 requests; two of three runs reproduced
`RemoteProtocolError` failures and safely stopped. The remaining run first
failed at concurrency 256. No v3 result reported an application 5xx, and
post-run container inspection found no OOM kill or runtime error.

## Capacity boundary

V2 established 64 as its highest repeatedly reliable tier because formal
request failures appeared at 96 in two of three runs. V3 established a repeated
correctness lower bound of 96, with the first reproduced request-failure tier
moving to 128. This is a reliability-boundary improvement, not a claim that 96
is an efficient production operating point.

The performance recommendation remains concurrency 64. In every v3 run,
moving from 64 to 96 reduced throughput and sharply increased P95 latency. At
96, the larger pool reached 38--39 checked-out connections and the overflow
ceiling of 20, while sampled CPU remained 34.4--43.1% and sampled memory stayed
below 134 MiB. The larger pool reduced queueing but shifted rather than removed
the next constraint.

## Engineering interpretation

The optimization supports the connection-pool hypothesis: the unchanged C64
throughput baseline, improved C96 medians, and removal of C96 request failures
are consistent with additional pool capacity helping under contention. The
remaining C96 latency growth and pool saturation show that pool sizing alone is
not sufficient. Future experiments should isolate transaction lifetime,
idle-in-transaction state, Docker forwarding, and multi-worker behavior rather
than increasing the pool again without a PostgreSQL connection budget.

## Recommendation

Use 64 as the performance-safe local tier for this one-worker configuration and
treat 96 as a tested correctness lower bound with poor tail-latency headroom.
Do not claim reliable capacity at 128. If higher concurrency is required,
measure a separately versioned architecture change, such as shorter database
connection lifetime or multiple workers with an explicit total connection
budget.

## Limitations

These are local Docker Desktop results using deterministic provider stubs, one
Uvicorn worker, real local PostgreSQL, and no OpenAI, S3, or Langfuse traffic.
Host load affected run-to-run latency. The evidence does not establish a
production SLO, cloud-provider throughput, multi-host capacity, or universal
maximum concurrency.
