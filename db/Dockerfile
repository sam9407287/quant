# TimescaleDB image with project schema and seed baked in.
#
# On a fresh volume, the postgres entrypoint runs every script under
# /docker-entrypoint-initdb.d/ in lexicographic order, so the database
# starts up already configured with hypertables, Continuous Aggregates,
# refresh/compression policies, and the roll_calendar seed.
#
# These scripts only run once (when the data directory is empty). Schema
# changes after that must be applied out-of-band via psql or a migration
# tool — the same constraint as any production PostgreSQL deployment.
FROM timescale/timescaledb:latest-pg16

COPY db/schema.sql               /docker-entrypoint-initdb.d/01_schema.sql
COPY db/seed_roll_calendar.sql   /docker-entrypoint-initdb.d/02_seed.sql
