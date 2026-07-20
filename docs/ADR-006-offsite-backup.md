# ADR-006: Off-Site Backup to Cloudflare R2

- **Status:** Accepted — implemented 2026-07-20; activation pending R2 credentials (§5)
- **Date:** 2026-07-20
- **Deciders:** Sam

## 1. Context

ADR-001 chose a self-hosted TimescaleDB on Railway (the managed plugin
lacks the `timescaledb` extension) and explicitly accepted "no managed
backups". STATUS.md §7 has since flagged that as *the highest
production risk in the system*. There were zero backups.

The risk is asymmetric in a way that matters:

| Data | Recoverable after a total loss? |
|---|---|
| Purchased vendor history (e.g. FirstRate 2008→purchase date) | **Yes** — re-load from the vendor CSVs, which are kept as master copies |
| Bars accumulated by the daily fetcher | **No** — yfinance serves only ~7 days of 1m bars |
| users / strategies / backtest runs | **No** (small, but irreplaceable) |

So every day of operation adds unrecoverable data. IBKR was considered
as a recovery path but only backfills roughly six months of intraday
futures data under strict pacing limits — a partial net, not a plan.

## 2. Decision

Back up to **Cloudflare R2** (S3-compatible; 10 GB storage free, zero
egress fees, so a restore costs nothing).

**CSV, not `pg_dump`.** Backups are gzipped CSV written with the S3
API. A restore therefore needs no `pg_dump`/server version match:
apply `db/schema.sql` (idempotent) and `COPY` the files back — the same
shape as the existing `scripts/bootstrap_csv.py` load path.

**Monthly partitions for bars.** `kbars_1m/YYYY-MM.csv.gz`. The current
month is re-uploaded every run; earlier months are complete and are
skipped once present (`--rewrite-all` forces a full rewrite, e.g. after
loading purchased history). This keeps daily upload volume proportional
to new data instead of total data.

**Whole-table snapshots for the small tables** (`users`, `strategies`,
`backtest_runs`, `backtest_trades`, `roll_calendar`, `experiments`)
under `tables/YYYY-MM-DD/`, giving day-granular point-in-time recovery
for account and research state.

**`BACKUP_SINCE` (default `2026-07-20`)** bounds what is backed up.
Bars older than that date are vendor history and re-loadable from the
purchased CSVs; there is no reason to pay to store them twice.

**Chained to the daily fetch**, not a separate schedule: the backup
runs immediately after ingestion inside `run_daily_fetch`, so it always
captures the freshest bars. A backup failure is logged and swallowed —
it must never fail the ingestion that produced the data.

## 3. Consequences

- New dependency: `boto3`. New settings: `R2_ACCOUNT_ID`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
  `BACKUP_SINCE`. Missing credentials **disable** the job with a
  warning rather than erroring.
- Worst-case data loss becomes one day (the window between the last
  backup and the failure), down from everything.
- At current volume (~870k bars) a monthly partition is a few MB. Even
  35 symbols × 18 years (~165M bars) compresses to a few GB — within or
  near the free tier, and R2 storage beyond it is ~$0.015/GB/month.

## 4. Restore procedure

1. Provision a fresh TimescaleDB and apply `db/schema.sql`.
2. Download `kbars_1m/*.csv.gz` and `tables/<latest-date>/*.csv.gz`.
3. `COPY kbars_1m (instrument, ts, open, high, low, close, volume, source) FROM …`
   per month file, then each small table.
4. Re-load purchased vendor history for dates before `BACKUP_SINCE`.
5. `fetcher.pipeline.refresh_continuous_aggregates()` to rebuild the
   higher timeframes (they are derived — never backed up).

## 5. Activation runbook

1. Cloudflare dashboard → R2 → create bucket (e.g. `quant-futures-backup`).
2. R2 → Manage API Tokens → create token with **Object Read & Write**
   scoped to that bucket. Note the Access Key ID, Secret Access Key,
   and the Account ID from the R2 overview page.
3. Set on the Railway **fetcher** service: `R2_ACCOUNT_ID`,
   `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
4. Verify: `railway ssh --service fetcher -- python -m fetcher.backup`
   then confirm the objects in the R2 browser.
