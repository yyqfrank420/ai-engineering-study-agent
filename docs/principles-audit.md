# Principles audit

Audit date: 2026-07-18

Sources:

- `Engineering Principles.pdf` supplied by the project owner
- `AI Principles.pdf` supplied by the project owner
- the settled combined worktree, including application code, prompts, storage,
  migrations, infrastructure, CI, tests, and contributor documentation

No live model call, deployment, production migration, or production-data mutation was
performed during this audit.

## Outcome

The active build was reviewed after the parallel backend and frontend work finished. The
repository now has one canonical engineering standard, durable retry and admission
boundaries, explicit model trust boundaries, prompt release fingerprints, safer transport
semantics, and broader automated verification. The changes are local and require normal
review and rollout; the new database migrations have not been applied to production.

## Strong foundations retained

| Principle | Evidence in the audited worktree |
| --- | --- |
| Shared AI platform | Model calls remain behind the LLM adapter, with configurable Anthropic/OpenAI routing and fallback. |
| Models treated like code | Prompts and model settings are source controlled, prompt SHA-256 is recorded in telemetry, focused regressions cover contracts, and staging cases gate representative behaviour. |
| Canonical persistent data | Production state is Supabase Postgres; storage models, RLS startup validation, Alembic, and atomic completed-turn persistence are present. |
| Graceful degradation | Model fallback, bounded streams and queues, timeouts, optional research degradation, and diagram suppression after failed review are explicit. |
| Constrained actions | Runtime tools are read-only retrieval/design capabilities; no general external mutation tool is exposed. |
| Layered evaluation | Deterministic validation, an independent architecture critic, private browser rendering, unit/integration tests, artifact validation, and live staging cases cover different failure modes. |

## Corrections made during the audit

### Durable retries, races, and canonical state

- Completed chat turns are keyed by `client_request_id` at the database boundary. A retry
  replays the canonical stored assistant response instead of paying for or persisting a
  second answer.
- The transport owns the terminal `done` event and emits it only after the complete turn is
  committed. Cancelled or failed drafts cannot falsely look durable to the browser.
- Thread count/evict/create, active-stream admission, chat request limits, OTP limits,
  internal-login limits, and public analytics limits now use transactions or advisory locks.
- Shared rate-limit rows contain HMAC-derived keys rather than raw email addresses, user IDs,
  or IP addresses, and expired reservations are pruned from the canonical table.
- SQLite now enforces foreign keys so local tests cannot construct states that production
  Postgres rejects.

### AI and transport boundaries

- Shared prompt protection is applied to external context and progressive explanation blocks.
  Model arrays/objects are type-checked and normalised before use; malformed scalar collection
  fields, truthy string booleans, duplicate IDs, and oversized fallbacks are rejected or bounded.
- Deterministic graph review requires approval/write controls only when the requested system
  actually performs external mutations, avoiding invented policy machinery in read-only designs.
- Prompt fingerprints, effective model, provider, effort, sampling controls, operation, and
  fallback status are recorded for release traceability.
- WebSocket commands are bound to the active client request, queued safely across the auth/start
  handshake, and cancelled tasks are awaited. SSE cancellation now awaits the agent task as well.
- Client request IDs use browser UUIDs rather than short `Math.random()` fragments.

### Security, UI, CI, and maintainability

- Error logs at sensitive boundaries record exception types without provider payloads, tokens,
  request content, or user-supplied values. JWT header parsing uses the JWT library rather than
  manual base64/JSON handling.
- The frontend ignores stale stream IDs, resets cancelled drafts, does not double-count
  `error` plus `done`, blocks remote Markdown images, and keeps unapproved graphs private.
- Applied diagrams no longer shimmer forever when enrichment is intentionally absent, and the
  staging renderer reports only edges it actually drew.
- Python and frontend dependency audits are explicit CI gates. Pillow is pinned to the patched
  runtime release; evaluation dependencies are separated from production dependencies.
- Ingestion tests no longer contain a machine-specific PDF path or load a heavyweight model at
  collection time. Unit coverage injects a fake model; source-PDF and real-model checks are
  explicit opt-in integrations.
- Cloud Run detection is part of the canonical settings object, and production validation now
  rejects disabled concurrency, authentication, analytics, and request-rate limits.

## Repository-wide instructions

- `docs/engineering-principles.md` is the canonical standard.
- `AGENTS.md` applies it to Codex and compatible repository agents.
- `CLAUDE.md` applies it to Claude Code.
- `.cursor/rules/engineering-principles.mdc` applies it to Cursor.

These files point to one source instead of maintaining divergent copies.

## Migration rollout and recovery

Apply migrations `20260718_0003` through `0005` in the existing pre-deploy migration job,
before routing traffic to the new backend. They are additive: RLS is enabled on the Alembic
version table, `client_request_id` is added as nullable before its partial unique index is built
concurrently, and the isolated `rate_limit_events` table and indexes are added.

After migration, verify that Alembic reports revision `20260718_0005`, all required tables have
RLS enabled, `chat_messages.client_request_id` exists, and these indexes resolve in `public`:
`uq_chat_messages_client_turn_role`, `idx_rate_limit_key_type_expiry`, and
`idx_rate_limit_expiry`. Both the migration script and backend startup now fail closed when the
required tables/RLS or durable-boundary columns/indexes are missing.

If application rollout fails, roll back the application revision and leave the additive schema in
place; the old code tolerates the nullable column and unused table. Prefer a forward fix over a
schema downgrade. Use the Alembic downgrade only before the new application has accepted traffic,
because removing the idempotency column or limiter table after use would discard recovery and
abuse-protection state.

## Verification

- Backend: **356 passed**, with one known `langchain-community` FAISS sunset warning.
- Focused diagram/staging verification after the Pillow upgrade: **37 passed**.
- Ingestion: **7 passed, 10 skipped**; skips are the documented source-PDF and real-model
  integrations because neither opt-in input was supplied.
- Frontend: **15 files / 95 tests passed**; ESLint and the TypeScript/Vite production build passed.
- Ruff, Bandit using the CI policy, `pip check`, canonical graph artifact validation, workflow YAML
  parsing, shell syntax, and `git diff --check` passed.
- `npm audit --omit=dev` reported **0 vulnerabilities**.
- CI now resolves and audits the backend runtime, evaluation, and ingestion requirement sets.
  Local full `pip-audit -r` resolution was not used as release evidence because this Intel macOS
  environment cannot resolve the Linux-only production Torch set; CI Linux is authoritative.

## Deliberately deferred or rollout-dependent

1. **Long-range memory remains a product/privacy design.** Conversation history is durable, but
   inspectable/correctable/deletable structured user facts are not implemented. They should not be
   inferred silently from transcripts.
2. **The compatibility SSE endpoint still accepts a missing `client_request_id`.** The production
   frontend and WebSocket protocol always supply one. Making it mandatory for legacy callers is an
   API contract change and should use a deprecation window or versioned endpoint.
3. **Postgres contention needs staging evidence.** SQLite concurrency tests and Postgres advisory
   lock paths are covered locally, but no live multi-connection production-like race test ran here.
4. **Clock injection remains incremental.** New rate-limit storage accepts an injected epoch, while
   older analytics/storage paths still read time internally. Hoist those clocks when their owning
   paths are next changed.
5. **FAISS integration migration is still owned work.** `langchain-community` emits a sunset
   warning; move to the supported standalone integration before it becomes a compatibility or
   security blocker.
6. **Migrations `20260718_0003` through `0005` need independent review and rollout.** Apply them
   before the backend revision, verify RLS/table/index state, and retain forward-recovery steps.
