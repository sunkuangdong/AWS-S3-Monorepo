# Capacity v1/v2 Comparison

## Outcome

Capacity v1 established a tested local lower bound of 64 concurrent clients.
Capacity v2 extended the search above that boundary and reproducibly identified
concurrency 96 as the first saturation candidate. For this one-worker local
configuration, 64 is therefore the highest fully reliable tested tier; 96
should not be used as a default operating point without architectural changes.

## Evidence boundary

| Dimension | Capacity v1 | Capacity v2 primary run |
| --- | ---: | ---: |
| Protocol | 1.0.0 | 2.0.0 |
| Requests per measured tier | 200 | 1,000 |
| Warm-ups per tier | 5 | 64 |
| Highest fully reliable tier | 64 | 64 |
| First saturation candidate | Not observed through 64 | 96 |
| Concurrency 64 success | 100% | 100% |
| Concurrency 64 throughput | 165.047 RPS | 190.760 RPS |
| Concurrency 64 P95 | 511.634 ms | 609.678 ms |
| Concurrency 96 success | Not tested | 99.8% |
| Concurrency 96 throughput | Not tested | 68.018 RPS |
| Concurrency 96 P95 | Not tested | 4,690.003 ms |
| Cloud calls and cost | 0 / $0 | 0 / $0 |

The concurrency-64 throughput values are not an optimization comparison. v2
used five times as many measured requests per tier, more warm-ups, a different
sampling interval, and a different run. They show that the baseline remained
functional, not that application code became 15.6% faster.

## Repeated Capacity v2 signal

All three v2 executions marked concurrency 96 as a saturation candidate:

| Run | C64 success / RPS / P95 | C96 success / RPS / P95 | Stop tier |
| --- | --- | --- | ---: |
| `20261018T010213Z` | 100% / 165.910 / 804.597 ms | 99.9% / 70.147 / 4,352.453 ms | 96 |
| `20261018T010858Z` | 100% / 134.713 / 1,095.360 ms | 100% / 102.036 / 3,083.174 ms | 192 |
| `20261018T011246Z` | 100% / 190.760 / 609.678 ms | 99.8% / 68.018 / 4,690.003 ms | 96 |

Across these runs, increasing concurrency from 64 to 96 reduced throughput by
24.3% to 64.3% while increasing P95 latency by 181.5% to 669.3%. Two runs also
observed formal POST transport failures at 96. The middle run reached higher
tiers, but its non-monotonic rebound at 192 does not invalidate the repeated 96
signal and must not be presented as a stable 192-client capacity claim.

## Bottleneck interpretation

At concurrency 96 in the primary run, the API container remained healthy, had
no restart or OOM, reported no HTTP 5xx or application traceback, and used
about 40% average CPU with roughly 135 MiB peak sampled memory. The SQLAlchemy
pool reached 14 checked-out connections with overflow 10, while PostgreSQL had
at most four active connections. This is evidence of queueing around the
single-worker application/connection-pool/local transport path rather than a
CPU or memory ceiling. It is an inference, not proof of one exclusive root
cause.

## Engineering changes in v2

- isolated service, port, runner, manifest, results suffix, and application
  identity so Capacity v1 remained immutable;
- high-concurrency tiers 64/96/128/192/256 with 1,000 measured requests each;
- concurrency-normalized marginal scaling efficiency and explicit unexecuted
  tier reporting;
- safe stop after a warm-up or measured request failure;
- cgroup, PostgreSQL, and SQLAlchemy pool sampling every 50 ms;
- one retry only for verification-read transport failures, never for measured
  POST requests; and
- privacy-safe, run-scoped PostgreSQL verification that avoids unbounded
  historical table scans.

## Recommendation

Use concurrency 64 as the tested local ceiling for the current one-worker
configuration, with operational headroom below it. Before retesting 96 and
higher, tune or redesign the application database-pool and request-handling
path, then create a new protocol version. Multi-worker tests should be a
separate experiment because they change the architecture rather than merely
repeat Capacity v2.

## Limitations

These results use Docker Desktop, one Uvicorn worker, local PostgreSQL, and
deterministic provider stubs. They exclude real OpenAI/S3 latency and quotas,
production networking, multi-host scheduling, and end-user traffic. They do
not establish a production SLO or a universal maximum capacity.
