# Multi-stage build for the Next.js dashboard.
#
# `output: "standalone"` in next.config.mjs makes the runner stage a thin
# Node container that only ships the compiled server, the static assets,
# and the trimmed node_modules tree the standalone bundle actually needs.
#
# Build context is the repository root (Railway invokes Docker with the
# repo root as context for every service in railway.toml), so all COPY
# paths are prefixed with `frontend/`.

FROM node:20-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

# ---------- deps ----------
# A dedicated stage for `pnpm install` lets Docker reuse the layer whenever
# only application code changes — installs dominate build time otherwise.
FROM base AS deps
WORKDIR /app
RUN apk add --no-cache libc6-compat
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ---------- builder ----------
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN pnpm build

# ---------- runner ----------
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

# Run as a non-root user — matches the security posture of the API and
# fetcher images (see `Dockerfile`, `Dockerfile.fetcher`).
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# `standalone` produces a self-contained server.js plus a minimal
# node_modules. Static assets and the optional public/ folder must be
# copied in separately because Next does not bundle them into standalone.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
