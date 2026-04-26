# Quant Futures — Frontend

A small Next.js 14 dashboard that renders the data the FastAPI backend exposes
under `/api/v1/...`. It exists for two reasons:

1. **Visibility.** Railway's built-in database UI only renders for its
   first-party Postgres template; the self-hosted TimescaleDB Docker service
   has no equivalent, leaving operators with `psql` or third-party GUIs as the
   only ways to inspect ingested data. A browser-based view that talks to the
   API removes that gap without re-exposing the database.
2. **Foundation.** `CLAUDE.md` and the project README have always promised a
   React/Next.js charting dashboard for Period 2 (signals visualisation) and
   Period 3 (live order/PnL stream). This is the seed.

## Stack

| Layer        | Choice                                  |
| ------------ | --------------------------------------- |
| Framework    | Next.js 14 (App Router) + React 18      |
| Language     | TypeScript (strict)                     |
| Styling      | Tailwind CSS 3                          |
| Charting     | TradingView `lightweight-charts` v4     |
| Data fetching| Native `fetch` from server components   |

No global state library, no React Query — the app is small enough that
co-locating fetches in server components keeps the mental model flat.

## Pages

| Route        | Source                                   | Purpose                                       |
| ------------ | ---------------------------------------- | --------------------------------------------- |
| `/`          | server, calls `GET /api/v1/coverage`     | Per-instrument summary cards + quick links    |
| `/coverage`  | server, calls `GET /api/v1/coverage`     | Full `(instrument × timeframe)` matrix        |
| `/chart`     | client, calls `GET /api/v1/kbars`        | Interactive candlestick + volume chart        |

## Local development

Prerequisites: Node 18+ and pnpm 9+.

```bash
cd frontend
cp .env.local.example .env.local   # optional — defaults point at production

pnpm install
pnpm dev                            # http://localhost:3000
```

The dev server defaults to the deployed Railway API
(`https://quant-production-d645.up.railway.app`), so you can browse data
immediately without running the backend locally. Override `NEXT_PUBLIC_API_URL`
in `.env.local` to point at `http://localhost:8000` when iterating on the API.

## CORS

The FastAPI backend reads its allow-list from the `CORS_ORIGINS` env var
(comma-separated). For local dev, the default `http://localhost:3000` is
already permitted. When this dashboard is deployed, add its public URL to
`CORS_ORIGINS` in the Railway dashboard for the `quant` service — otherwise
the browser will block the cross-origin requests.

## Scripts

```bash
pnpm dev        # next dev
pnpm build      # next build
pnpm start      # next start (after build)
pnpm lint       # next lint
pnpm typecheck  # tsc --noEmit
```

## Deployment

Out of scope for the initial drop. Vercel, Railway and self-hosted Node all
work; pick once the API surface stabilises in Period 2.

## Files

```
frontend/
├── app/
│   ├── layout.tsx            # Shell + nav
│   ├── page.tsx              # Dashboard (server component)
│   ├── coverage/page.tsx     # Coverage table page
│   └── chart/page.tsx        # Chart page (delegates to client component)
├── components/
│   ├── nav.tsx
│   ├── coverage-table.tsx
│   └── chart-view.tsx        # "use client" — owns lightweight-charts
├── lib/
│   ├── api.ts                # Typed wrappers around fetch()
│   └── types.ts              # Mirrors the FastAPI Pydantic models
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.mjs
└── .env.local.example
```
