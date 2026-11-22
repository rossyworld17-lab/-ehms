# Performance review — release 1.0

## Method
- **Data**: the demo hotel (26 rooms) plus one year of generated history — 2,250 stays, 8,550 folio lines,
  29,700 journal lines, 2,255 payments (`backend/tools/generate_volume.py`, demo databases only).
- **Server**: PostgreSQL 16 and the application (2 Uvicorn processes, connection pool of 10 per process) on one
  4-vCPU / 15 GB virtual machine; the load generator ran on the same machine, so the figures are conservative.
- **Load**: `backend/tools/loadtest.py` — virtual users repeating a realistic mix (dashboard, room board, arrivals,
  availability, folio, reservation search, occupancy report, BI analytics, assistant question, POS orders) with a
  short think time (0.2 s at 20 users, 0.1 s at 50 users — far busier than real staff).

## Results (after the 1.0 optimisations)

| Users | Requests/s | Errors | p50 | p95 | p99 |
|---|---|---|---|---|---|
| 20 | 95 | 0 | 7 ms | 21 ms | 36 ms |
| 50 | 291 | 0 | 58 ms | 170 ms | 232 ms |

Per request type at 20 users (p50 / p95, ms): dashboard 10 / 23, room board 3 / 12, availability 4 / 13,
arrivals 13 / 23, folio 4 / 15, reservation search 13 / 22, occupancy report 5 / 17, BI analytics 15 / 35,
assistant 5 / 16, POS orders 3 / 10.

## Optimisations made in 1.0

| Change | Effect |
|---|---|
| PostgreSQL connection pool (`EHMS_DB_POOL_SIZE`, default 10 per process) instead of a new connection per transaction | removes several milliseconds from every request |
| Dashboard trend and forecast computed with range queries (3 queries instead of ~150) — results verified identical | dashboard p50 at 20 users 41 → 10 ms; p95 at 50 users 538 → 232 ms |
| Occupancy report uses the same range computation | p50 31 → 5 ms |
| 20 indexes for the busiest lookups (migration 0010) | front desk, folio, ledger, report and worker queries use indexes |

Before these changes the 50-user run gave 229 requests/s with an overall p95 of 385 ms; after, 291 requests/s and
170 ms.

## Capacity guidance
- A single 2–4 vCPU server comfortably serves a 50–150-room hotel (typically 10–40 concurrent staff). The load
  above corresponds to several times that activity.
- For larger or multi-property deployments, raise `WEB_CONCURRENCY` (processes ≈ vCPUs), keep
  `processes × EHMS_DB_POOL_SIZE` below PostgreSQL's `max_connections` (100 by default), and run the worker as a
  separate process (`EHMS_WORKER=0` on web processes, `python -m ehms.worker --loop` once).
- Heavy reports and BI ranges up to two years are bounded; very large exports should be scheduled (Insights →
  Scheduled reports) rather than run at peak times.

## Re-running
```bash
DATABASE_URL=postgresql://…/ehms_staging EHMS_SECRET_KEY=… python backend/tools/generate_volume.py --days 365
```
```bash
python backend/tools/loadtest.py --base https://staging.example.com --users 20 --seconds 60
```
