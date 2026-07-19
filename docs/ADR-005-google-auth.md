# ADR-005: Google Sign-In + Per-User Data Ownership

- **Status:** Accepted — implemented 2026-07-20; production activation
  pending the Google OAuth Client ID (see §5)
- **Date:** 2026-07-20
- **Deciders:** Sam

## 1. Context

The platform opens to a small group of testers. Requirements: each
user owns their strategies and backtest runs (admin sees everything),
sign-in via Google, zero hosting changes (everything stays on
Railway), zero cost.

## 2. Decision

**Google is only the identity provider.** The frontend obtains an ID
token from Google Identity Services; the FastAPI service verifies it
locally (google-auth, cached Google certs) — no session store, no
auth service, no new infrastructure.

- `users` table keyed on `google_sub`; row upserted every
  authenticated request; `role` re-derived from the `ADMIN_EMAILS`
  allowlist at sign-in (no management UI).
- `strategies` and `backtest_runs` gain `owner_id` (NULL = legacy
  rows). `CurrentUser.owner_filter` is None for admins (unfiltered)
  and the user id otherwise; repositories take it as a bound
  parameter. Admin listings include `owner_email`.
- Protected: all of /api/v1/strategies and /api/v1/backtest, plus
  POST /api/v1/ml/train (compute cost). Public read-only: kbars,
  coverage, roll-calendar, GET ml/experiments (server-rendered page),
  health.
- Frontend: GIS button island in the nav; ID token in sessionStorage;
  Authorization header injected in the strategy/backtest clients and
  trainModel; RequireAuth gate cards on the research pages; chart's
  strategy dropdown disabled until signed in. Token expiry (~1h)
  surfaces as 401 → sign in again (no silent refresh in v1).
- Fixed in passing: CORS `allow_methods` lacked PUT/DELETE, so
  strategy update/delete from the browser was blocked by preflight.

## 3. Cost

$0. Google OAuth has no usage fee; the unverified consent screen in
testing mode allows up to 100 named test users — add friends' Gmail
addresses in the GCP console.

## 4. Testing strategy

Integration tests override the `get_current_user` dependency (no real
tokens minted): isolation matrix proves user A cannot list/get/
update/delete/evaluate user B's strategies or read B's runs, admin
sees all with owner attribution, unauthenticated writes are rejected
while kbars stays public. Token verification error paths are
unit-tested against a mocked google-auth.

## 5. Activation runbook (production)

1. GCP console → OAuth consent screen (External, Testing) → add test
   users; Credentials → OAuth Client ID (Web application) with JS
   origins `https://frontend-production-d637.up.railway.app` and
   `http://localhost:3000`.
2. Railway `quant` (api) service: set `GOOGLE_OAUTH_CLIENT_ID=<id>`
   and `ADMIN_EMAILS=sam9407287@gmail.com`; redeploy.
3. Railway `frontend` service: set `NEXT_PUBLIC_GOOGLE_CLIENT_ID=<id>`
   and **redeploy** (build-time var — STATUS.md §5.L).
4. Apply schema to prod DB (idempotent):
   `railway ssh --service timescaledb -- psql -U quant -d quant_futures -v ON_ERROR_STOP=0 -f /docker-entrypoint-initdb.d/01_schema.sql`
5. Sam signs in once (creates the admin users row), then adopt legacy
   rows: `UPDATE strategies SET owner_id = (SELECT id FROM users WHERE email='sam9407287@gmail.com') WHERE owner_id IS NULL;` (same for backtest_runs).

Until step 2, the API answers 503 on protected endpoints ("sign-in is
not configured"); until step 3, the frontend hides the sign-in button
and gates pass through — the backend remains the enforcement point.
