# webapp-bus-executor — DispensaryIQ bus binding

**Brief:** #370 (Stage 4 kickoff)
**Status:** Plumbing + authority ceiling only. No route-check machinery yet (Stage 1/#TBD).

This document is the convention the dip-service bus (`cc_briefs` / `cc_reports`,
Neon project `lively-wave-36623660`) uses to route web-surface work to this repo,
mirroring the existing dip-bus-executor pattern used for `Ed-Dobbles-LLC/dip-service`.

## Bound repo + branch

- Repo: `Ed-Dobbles-LLC/DispensaryIQ`
- Base branch: `main`
- Layout in scope: `site/` (static HTML/JS), `scripts/` (route logic), `Dockerfile`,
  `Caddyfile`, `railway.json`, `.github/workflows/`, `docs/`, `README.md`

## Claim convention for web briefs

A brief is a **web brief** when `cc_briefs.project = 'dip'` AND
`cc_briefs.title LIKE '[WEB]%'`.

This uses the existing `title` column rather than a new `surface` column —
zero schema migration, trivially reversible (it's a string convention, not a
DB change). If a dedicated `surface` column is wanted later, it should be
`ALTER TABLE cc_briefs ADD COLUMN surface text` (nullable, no backfill
required — the `[WEB]` prefix keeps working as a fallback).

Claim SQL (same fencing pattern as the standard bus protocol in
`docs/RUNBOOK_autonomous_execution.md` / repo `CLAUDE.md`):

```sql
UPDATE cc_briefs
   SET status='claimed', lease_owner=:worker_id, agent=:agent,
       attempts=attempts+1, claim_version=claim_version+1,
       claimed_at=now(), started_at=now(), heartbeat_at=now(),
       lease_expires_at=now() + (COALESCE(lease_minutes,30)||' min')::interval,
       max_runtime_at=now() + interval '30 min'
 WHERE brief_id=(
   SELECT brief_id FROM cc_briefs
    WHERE status='pending' AND project='dip' AND title LIKE '[WEB]%'
      AND (next_run_at IS NULL OR next_run_at<=now())
    ORDER BY priority, created_at
    LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING brief_id, claim_version;
```

## Authority ceiling (hard)

**PR + preview + evidence ONLY.** The executor may not merge-to-main or
promote-to-prod any change that alters a Curaleaf-facing pitch page.

- **Pitch-facing (pause `needs-ed-review`, same ONE HARD EXCEPTION as
  pitch-certified data):** any `site/*.html` page a live pitch reads from —
  currently `index.html`, `coverage.html`, `outlet.html`, `market-share.html`,
  `named-accounts.html`, `territory.html`, `price-comparison.html`,
  `price-compliance.html`, `products.html`, `display-quality.html`,
  `shelf-quality-explainer.html`, `week-over-week.html`, `pricing.html`,
  `ny-find.html`, and their shared `site/assets/*` — plus `site/data/*` feeding
  them. Every PR touching these opens, posts preview evidence, and stops.
- **Non-pitch-facing (may auto-merge on CI-green once repo policy allows):**
  `README.md`, `docs/*`, `.github/workflows/*`, ops-only surfaces
  (`site/cpo.html`, `site/quality.html`, `site/alerts.html` — internal dashboards, not
  client-facing). Until Stage 1 route-checks exist, these still open a PR and
  pause rather than auto-merge — see "Report" note below.
- Every claimed web brief posts a `cc_reports` row with `preview URL +
  deployed SHA` before returning to `pending`/`done`.

## Preview-deploy mechanism (documented, not live-verified this session)

Railway project `48c614a5-ccfb-4b97-85a9-0c6454869a80`, service `d0357e6e`.
No Railway MCP connector was available in this session, so this reflects the
repo's own documentation (`README.md`) rather than a live API check:

- `railway.json` builds from `Dockerfile` (Caddy 2.8 alpine serving `site/`
  as static files). `README.md` states push-to-`main` auto-redeploys in
  ~60s. That is a **branch deploy of `main`**, not a per-PR preview.
- Railway does not have a per-PR ephemeral preview environment configured
  for this service (no PR-environment config present in `railway.json` or
  the repo). Confirming/enabling native Railway PR previews requires
  Railway dashboard access this session does not have.
- **Gap for Stage 1:** until native PR previews exist, "preview" for this
  executor means CI-green (build + `caddy validate`) on the branch, not a
  live URL a reviewer can click. Stage 1 route-checks should either (a)
  enable Railway's PR-environment feature for this service, or (b) run
  Playwright against a manually-deployed branch/staging Railway
  environment. Flagging this rather than guessing which Ed prefers.

## Durable trigger — known gap

This session's own tools (`CronCreate`/`CronList`) are **session-scoped**:
jobs live only in the firing session's memory and are gone when the session
ends (max 7-day auto-expiry even if the session stayed alive). They cannot
durably bind a polling loop to this repo the way the `cc-dispatcher` Railway
service does for dip-service (see `command-center/AUTONOMY_LOOP.md`).

Standing up a durable, cross-session webapp-bus-executor — one that
automatically claims `[WEB]` briefs without a human/Routine firing a session
each time — requires either:
1. Extending `cc-dispatcher`'s `fire_execution` to accept a target-repo
   parameter and route `[WEB]`-claimed briefs to `Ed-Dobbles-LLC/DispensaryIQ`
   instead of `dip-service`, or
2. A product-level Claude Code Routine (the same mechanism that fired this
   very session via `brief_id=370`) configured to poll for
   `project='dip' AND title LIKE '[WEB]%' AND status='pending'` and re-fire
   itself against this repo.

Neither is reachable from inside a single fired session — this is a
`cpo-decision-needed` follow-up, not something this brief can close.
