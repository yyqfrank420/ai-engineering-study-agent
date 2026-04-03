# Project Learnings — AI Engineering Study Agent

**Project:** AI-powered study assistant for Chip Huyen's *AI Engineering* (O'Reilly).
**Stack:** FastAPI · React/D3 · FAISS · Supabase · Cloud Run · Vercel · Terraform · GitHub Actions.
**Date range:** 2026-03-31 → present.

This document captures hard-won learnings across every layer of the project. Written as a reference for future projects — language is intentionally general where the lesson is transferable.

---

## 1. System Design

### 1.1 Transport: SSE over WebSockets for LLM streaming

- **What we used:** Server-Sent Events (SSE) — `text/event-stream` via a `POST` endpoint.
- **Why not WebSocket:** WebSocket is bidirectional and stateful. For a request-response LLM pattern that just needs to stream tokens back, SSE is simpler — no connection management, native browser support, works through proxies.
- **The catch:** The browser's native `EventSource` API only supports `GET` requests. We needed to send a JSON body, so we built a custom `fetch`-based SSE client (`sse.ts`). The hook is named `useWebSocket.ts` for historical reasons — don't be fooled by the name.
- **Lesson:** Don't reach for WebSocket when SSE does the job. Pick the simplest transport that fits the data flow direction.

### 1.2 Cold-start UX contract

- Cloud Run with `min_instances = 0` means the backend sleeps when idle. The first request after idle wakes it and loads FAISS (~few seconds).
- **Wrong approach:** Silently send the first chat message and let it fail or time out.
- **Right approach:** Explicit `Prepare` button → `GET /api/prepare` → readiness state machine (`unknown → preparing → ready`). Send is disabled until `ready`. This puts the user in control of when they pay the cold-start cost.
- **Lesson:** Design UX explicitly around infrastructure constraints. Don't hide latency — surface it gracefully.

### 1.3 Serverless DB connections need a transaction pooler

- Supabase exposes two pooler modes: session pooler (port 5432) and transaction pooler (port 6543).
- On Cloud Run, each instance can spawn and die rapidly. Session pooler holds a Postgres connection open for the duration of a client session — wasteful and connection-exhausting at scale.
- **Transaction pooler (port 6543)** is the correct choice for serverless. Each query borrows a connection, executes, and returns it immediately.
- **Lesson:** Always use the transaction pooler URL with serverless/container workloads. The port is the distinguishing detail: `5432` = session, `6543` = transaction.

### 1.4 Scale-to-zero cost tradeoff

- `min_instances = 0` means ~$0/month when idle. `min_instances = 1` means a constant ~$15-30/month.
- For a personal tool with irregular usage, the right default is `0`. The cold-start UX mitigation (the Prepare flow) makes it tolerable.
- **Lesson:** Don't pay for always-on unless you've measured that cold-start latency is genuinely unacceptable. Use free credits to measure first, then decide.

### 1.5 No load balancer needed at this scale

- Cloud Run comes with a public HTTPS `run.app` URL out of the box. A GCP external load balancer costs ~$18/month fixed even if zero traffic flows through it.
- For a single-region, single-service personal project, the `run.app` URL is sufficient.
- **Lesson:** A load balancer is for multi-region routing, TLS termination at custom domains, and WAF. Don't provision one reflexively.

---

## 2. AI Engineering

### 2.1 Agent pipeline: explicit asyncio vs. framework

- We started with LangGraph in the design spec. We shipped with a plain `asyncio` pipeline in `backend/agent/graph.py`.
- **Why we dropped LangGraph:** The pipeline is 4 phases, ~200 lines of control flow. LangGraph adds value when you need durable checkpointing, stateful retries, or human-in-the-loop interrupts. We didn't need any of those yet. Adding a framework to manage complexity we didn't have would've added complexity.
- **Lesson:** Use orchestration frameworks when you need their specific capabilities. A `for` loop and `asyncio.gather` are correct solutions for simple parallel fan-out.
- **When to revisit LangGraph:** Durable checkpointing / resume mid-run, multi-step retries with stateful recovery, human approval steps.

### 2.2 Model split: Sonnet for orchestration, Haiku for workers

- Orchestrator (routing + synthesis): `claude-sonnet-4-6` — needs reasoning quality.
- RAG worker, graph worker, node detail workers: `claude-haiku-4-5` — high volume, cost-sensitive, structured output.
- OpenAI SDK wired as a fallback after `llm_max_retries` Anthropic failures.
- **Lesson:** Not all calls need the same model. Route cheap, high-volume calls to cheaper models. Use the expensive model only where quality is critical.

### 2.3 Thinking tokens: where they add value vs. waste money

- Extended thinking (`budget_tokens=5000`) was enabled for synthesis in early design. Cost: ~$0.075/query extra at Sonnet 4.6 rates.
- **What we found:** Synthesis quality didn't justify the cost. Synthesis is constrained (130–200 words, flowing prose) — the LLM doesn't need deep reasoning, it needs good formatting.
- **Where thinking does add value:** Routing decisions (intent classification) — the orchestrator needs to correctly decide `simple / memory / search`. Getting this wrong wastes entire downstream pipeline runs.
- **Lesson:** Thinking tokens pay off when the task requires genuine multi-step reasoning before producing output. Formatting tasks don't qualify.

### 2.4 Synthesis quality: prose not bullets

- Early synthesis produced bullet-pointed summaries. Users read answers in a chat UI, not a dashboard.
- **What worked:** Flowing prose, 130–200 words, no "Story:"/"Walkthrough:" headers, no unexplained jargon. Write like an intelligent tutor, not a report generator.
- **Prompt pattern:** "Synthesise from the context below. Write 130–200 words of flowing prose aimed at an intelligent non-expert. No headers. No bullet points. No jargon without inline explanation. Use analogies where helpful."
- **Lesson:** LLMs default to bullet points because they're common in training data. Explicitly prohibit the formats you don't want. Specifying the word count constrains verbosity and forces concision.

### 2.5 LLM routing: when routing fails, the whole pipeline fails expensively

- The orchestrator routes every message: `simple → quick response`, `memory → session history`, `search → full RAG + research pipeline`.
- **Known failure mode:** Messages with session history often get routed to `memory`, which skips the RAG worker. The synthesiser gets no book context. The response is hallucinated or vague.
- **Lesson:** Routing is the highest-leverage prompt in the pipeline. Test it adversarially. A misroute wastes downstream compute and produces bad output. Monitor routing decisions in production.

### 2.6 Research worker: DuckDuckGo for web augmentation

- Added an optional web research worker using DuckDuckGo (no API key needed).
- Runs in parallel with RAG via `asyncio.to_thread` (DuckDuckGo client is synchronous).
- 3 queries per message, 6-bullet cap on output, noise domain filtering, silent fail on timeout.
- Injected into the graph worker and synthesis as `research_context` block.
- **Lesson:** `asyncio.to_thread` is the right pattern for wrapping synchronous I/O in an async pipeline. The silent-fail approach prevents one flaky external call from breaking the whole response.

### 2.7 Node enrichment: fire-and-forget async

- Graph nodes are enriched post-response (2 RAG searches per node, book refs extracted).
- Enrichment fires after the `done` SSE event — the user gets the response immediately, nodes fill in progressively.
- **Lesson:** Heavy work that doesn't affect the primary response should run asynchronously after `done`. Fire-and-forget with progressive UI updates is better UX than blocking the response.

---

## 3. Dataset Engineering (Ingestion Pipeline)

### 3.1 Parent-child chunking strategy

- **Problem with naive chunking:** Fixed-size chunks lose context. A 200-token chunk in the middle of a section has no surrounding explanation.
- **Solution:** Two-tier chunking.
  - **Child chunks** (~200 tokens): dense, used for embedding and FAISS retrieval (high precision).
  - **Parent chunks** (~1000 tokens): the surrounding section, surfaced at inference time (high context).
  - Retrieval finds the best child chunks → expands to parent chunks → sends parents to LLM.
- **Lesson:** Embed small, retrieve big. The embedding model doesn't need 1000-token windows — it needs semantically tight units. The LLM does need context — give it the full section.

### 3.2 Embedding model choice

- `sentence-transformers/all-MiniLM-L6-v2`: 22M parameters, 384-dim embeddings, runs comfortably on CPU.
- Chosen for: local inference (no API cost), fast enough for ingestion, good enough quality for single-book Q&A.
- **Lesson:** For a closed-domain single-source corpus, a small local model beats a large API-based embedding model on cost with negligible quality loss. The domain is narrow; the model doesn't need to generalise broadly.

### 3.3 FAISS index: bundle in Docker, don't download at runtime

- Initial design: download FAISS artifacts from a URL on cold start.
- **Problem:** Cloud Run cold starts + large download = unacceptable latency before the first request can be served.
- **Solution:** Commit the index files to the repo (`data/faiss/`, ~7MB) and `COPY data/faiss/ /data/faiss/` in the Dockerfile. The index is baked into the image.
- **Tradeoff:** The Docker image is ~7MB larger. Acceptable for a private repo with a static index.
- **Lesson:** For small, infrequently-changing artefacts, baking into the image eliminates a runtime dependency and improves startup reliability. Reserve the download pattern for large artefacts that change frequently.

### 3.4 GraphRAG: what it is and why we deferred it

- **Full Microsoft-style GraphRAG:** Build a persistent knowledge graph from the corpus at ingestion time (entity extraction, community detection, map-reduce global search). Heavy indexing pipeline, high complexity.
- **Why we didn't build it:** Single-book Q&A doesn't need global semantic search. The current FAISS retrieval + LLM-generated graph is sufficient.
- **What we might add later:** Light graph-aware RAG — stable concept graph artefacts at ingestion time to ground the graph worker's output. Not GraphRAG, just better index structure.
- **Lesson:** GraphRAG is an indexing architecture, not just a retrieval pattern. Don't build it unless you need global/community-level queries. For localised document Q&A, dense FAISS retrieval is the right default.

---

## 4. DevOps & Infrastructure

### 4.1 Docker builds in CI: registry cache is essential

- Without caching, every CI run reinstalls all Python dependencies from scratch. For a backend with `faiss-cpu`, `anthropic`, `sentence-transformers`, etc., this is 5–8 minutes per run.
- **Solution:** `docker buildx build` with registry-based layer cache:
  ```
  --cache-from type=registry,ref=<image>:buildcache
  --cache-to   type=registry,ref=<image>:buildcache,mode=max
  --push
  ```
- Cache is stored in Artifact Registry as a separate `:buildcache` tag. Warm runs skip the `pip install` layer entirely.
- **Critical gotcha:** The default Docker driver doesn't support registry cache export. Must add `docker/setup-buildx-action@v3` before the build step to get the `docker-container` driver.
- **Lesson:** Always add registry cache to Docker builds in CI. First run populates; subsequent runs are 4–8× faster. Cost of storing the cache in Artifact Registry is negligible.

### 4.2 `.dockerignore` and `.gitignore` are independent — both matter

- A file can be committed to git (not gitignored) but still excluded from the Docker build context by `.dockerignore`.
- We committed `data/faiss/` to git (removed from `.gitignore`), but `.dockerignore` had `data` — so the files were never passed to `docker build`. The COPY instruction silently failed with "not found".
- **Fix:** Use negation in `.dockerignore`: `data` followed by `!data/faiss`.
- **Lesson:** When a Docker `COPY` step fails with "not found" on a file you know exists, check `.dockerignore` before debugging the Dockerfile. The build context is filtered before the Dockerfile even runs.

### 4.3 npm cross-platform native bindings

- `npm ci` is strict: it installs exactly what's in `package-lock.json`. If the lock file was generated on macOS, it contains macOS-specific optional dependencies. On a Linux CI runner, packages like `@rolldown/binding-linux-x64-gnu` (Vite 6 / rolldown) are missing.
- **Fix:** In CI, drop the npm cache step and run `rm -f package-lock.json && npm install` instead of `npm ci`. This regenerates the lock file for the current platform.
- **Root cause:** npm optional dependencies are platform-specific. Lock files generated on one OS don't carry the optional deps for other OSes.
- **Lesson:** Never commit a `package-lock.json` generated on macOS if CI runs on Linux, for projects using packages with platform-native bindings (rolldown, canvas, sharp, etc.). Either regenerate in CI or use a cross-platform lock generation step.

### 4.4 Postgres service in CI for apps with DB lifespan connections

- FastAPI lifespan hooks run on test collection if the test runner triggers app import. If the app connects to Postgres during startup, CI without a running Postgres will fail with "connection refused".
- **Fix:** Add a `services: postgres:16` block to the test job in GitHub Actions. The service starts before tests run.
- **Lesson:** Any app that touches external services during startup/lifespan needs those services available in CI. Test your CI environment assumptions explicitly.

### 4.5 SQLite/Postgres dual-mode: fixture isolation in tests

- Backend supports SQLite (local dev, unit tests) and Postgres (CI with real DB URL, production).
- When CI sets `SUPABASE_DB_URL`, the app switches to Postgres mode. Unit tests that call `init_db()` directly expected SQLite — they broke.
- **Fix:** In the `temp_data_dir` pytest fixture, `monkeypatch.setattr(settings, "supabase_db_url", "")` to force SQLite mode for those tests.
- **Lesson:** Test fixtures must control all the settings that affect the code path under test, not just the obvious ones. Mode-switching config values are easy to miss.

### 4.6 GCP Workload Identity Federation (keyless auth)

- **Problem:** GCP organisation policies often block service account key creation. Even when allowed, long-lived JSON keys in GitHub Secrets are a security risk.
- **Solution:** Workload Identity Federation (WIF). GitHub Actions gets a short-lived OIDC token at runtime. GCP exchanges it for a temporary access token. No JSON key ever created or stored.
- **How it works:**
  1. GitHub generates an OIDC token for the workflow run.
  2. GCP WIF validates it against a configured pool/provider.
  3. If valid, returns a short-lived GCP access token scoped to a service account.
- **Required APIs:** `iamcredentials.googleapis.com` + `sts.googleapis.com` must be enabled.
- **Scope:** The WIF provider's `attribute_condition` should be scoped to the specific repo — `assertion.repository == 'owner/repo'`. This prevents other repos (including forks) from impersonating the CI service account.
- **Lesson:** Use WIF for any GCP + GitHub Actions integration. It's the current best practice. Never store SA JSON keys as long-lived secrets if you can avoid it.

### 4.7 GCP Secret Manager: secrets need versions, not just existence

- Creating a secret resource in Secret Manager (`gcloud secrets create`) or via Terraform is not the same as having a value. A secret with no versions will cause a Cloud Run deployment to fail at startup when the service tries to mount it.
- **Lesson:** After creating secrets, always verify they have at least one version with `gcloud secrets versions list <secret-id>`. Terraform `google_secret_manager_secret_version` resources are separate from the secret itself — easy to miss.

### 4.8 Vercel CI: pull project settings before build

- `vercel build` in non-interactive CI fails with "No Project Settings found locally" if the `.vercel/project.json` file isn't present.
- **Fix:** Add `npx vercel pull --yes --environment=production --token=$VERCEL_TOKEN` as a step before `vercel build`.
- **Why:** `vercel pull` downloads the project configuration (framework preset, build settings, env var references) to `.vercel/`. Without it, the build system doesn't know the project context.
- **Lesson:** Vercel's CLI assumes an interactive login flow by default. In CI, always pull project config first. This is not in most tutorial examples but is required in practice.

### 4.9 Terraform state vs. reality: tainted resources

- If a Terraform apply partially fails (e.g., creates a resource but the next step errors), Terraform may mark the resource as "tainted" — meaning it believes the resource is in a bad state and plans to destroy + recreate it on the next apply.
- **Fix:** `terraform untaint <resource>` before the next apply, if you can verify the resource is actually healthy.
- **Lesson:** Terraform state and real infrastructure can diverge. Before running `terraform apply` after a failure, always run `terraform plan` and read the plan carefully. Unexpected destroys are often tainted resources, not real changes.

### 4.10 Infrastructure as Code: import before you create

- If resources were created manually (or by a previous process) before Terraform managed them, Terraform will try to create them again — and fail with a 409 conflict.
- **Fix:** `terraform import <resource_address> <resource_id>` brings existing resources under Terraform management without recreating them.
- **Lesson:** Any time you're introducing Terraform to a project that already has existing infrastructure, `terraform import` every existing resource before the first `terraform apply`. Otherwise the first apply will fail on every resource that already exists.

---

## 5. Frontend Engineering

### 5.1 D3 in React: own the DOM, don't share it

- React and D3 both want to control the DOM. Conflicts produce flickering, lost state, or renders that fight each other.
- **Pattern used:** Give D3 an isolated `<svg>` ref. React controls everything outside it; D3 owns the SVG exclusively. React `useEffect` with the ref triggers D3 renders on data changes.
- **Lesson:** Pick one system per DOM region. Don't let React render SVG children and also run D3 selections on the same elements.

### 5.2 Portals for popups in constrained layouts

- Sidebar panels often have `overflow: hidden` for scroll containment. Absolutely-positioned popups inside them get clipped.
- **Fix:** Use `ReactDOM.createPortal(<Popup />, document.body)` + `position: fixed` coordinates derived from the trigger element's `getBoundingClientRect()`.
- **Lesson:** Any popup, tooltip, or dropdown that needs to escape its parent's overflow context should render into `document.body` via a portal. This is the correct, reliable solution — not fiddling with `z-index` or `overflow: visible`.

### 5.3 SSE with POST: custom fetch client required

- The browser's native `EventSource` only supports GET. POST + JSON body + SSE streaming requires a custom client.
- Pattern: `fetch()` with `Content-Type: application/json` and manual stream reading from `response.body.getReader()`. Parse each chunk for `data: {...}\n\n` SSE frames.
- **Lesson:** Whenever you need to send a request body with SSE, you need a custom fetch-based client. Budget time for this — it's 50–100 lines of non-trivial code (partial chunk handling, decoder, event parsing).

### 5.4 UI feedback for rate limits and thread limits

- When the thread limit (5) is reached, the "New chat" button goes greyed-out — it does NOT turn red or show an error.
- **Why:** Red = error = something broke. Greyed = disabled = expected boundary. Users understand greyed-out buttons as "not available right now" without anxiety.
- **Lesson:** Disabled states should communicate "expected limit reached", not "something failed". Use grey for limits, red for errors. These are different signals.

---

## 6. Security

### 6.1 Supabase JWT verification

- Never trust a client-supplied JWT without verifying it server-side.
- The backend verifies every request's `Authorization: Bearer <token>` via `supabase_auth_adapter.py` — checks signature, expiry, and issuer against `SUPABASE_JWT_ISSUER` + `SUPABASE_JWT_SECRET`.
- **Lesson:** JWTs are not opaque session tokens — they're signed claims. Anyone can construct a JWT payload. Always verify the signature and claims on the server. Never use `jwt.decode(..., options={"verify_signature": False})` in production.

### 6.2 Cloudflare Turnstile for CAPTCHA

- Turnstile (free plan) is used to gate auth and chat endpoints against automated abuse.
- The backend verifies the Turnstile token server-side against Cloudflare's siteverify API — client-side success alone is not trusted.
- Local dev test keys: site=`1x00000000000000000000AA`, secret=`1x0000000000000000000000000000000AA`. These always pass without showing a widget.
- **Lesson:** CAPTCHA verification must happen server-side. Client-side success is easily spoofed. The secret key validates that the user actually solved the challenge.

### 6.3 Prompt injection awareness

- Tool results and external content (DuckDuckGo research, user messages) should be flagged as potential injection vectors.
- The backend has a `prompt_injection_threshold` config and pre-flight checks on incoming messages.
- **Lesson:** Any content that enters an LLM prompt from outside your control (user input, external API results, web scrapes) is a potential injection vector. Validate and sanitise before injecting into prompts.

### 6.4 Row-Level Security in Supabase

- Supabase Postgres uses RLS policies to ensure users can only read/write their own data.
- Example: `chat_threads` has `USING (auth.uid() = user_id)` — a user can only query their own threads, even if they try to access another user's thread ID directly.
- **Lesson:** Never rely on application-layer auth alone for multi-tenant data. Database-level RLS is the defence-in-depth layer that prevents auth bypass bugs from becoming data leaks.

---

## 7. Decisions We Deferred (and Why)

| Decision | Deferred until | Rationale |
|---|---|---|
| LangGraph migration | Multi-step stateful pipelines needed | Current asyncio pipeline is ~200 lines and fully working. Framework adds complexity without solving a current problem. |
| Full GraphRAG | Global/community queries needed | Single-book Q&A doesn't require community detection or map-reduce search. Dense FAISS retrieval is sufficient. |
| Custom domain | Traffic justifies it | `run.app` + `vercel.app` URLs work fine. Custom domain adds DNS, cert management, and load balancer costs. |
| `min_instances = 1` | Cold-start UX becomes unacceptable | Measure first. The Prepare flow mitigates cold starts. Pay for always-on only when the data says it's worth it. |
| AWS migration | Project scope expands | Architecture is designed for portability (adapter pattern for LLM + DB). Migration is a config change + adapter swap, not a rewrite. |

---

## 8. Architecture Portability (AWS Migration Shim)

The project is designed to port cleanly to AWS. All infrastructure-touching code is behind `backend/adapters/`:

| Current | AWS equivalent |
|---|---|
| Anthropic SDK | Bedrock Converse Stream API |
| Supabase Postgres | RDS Aurora Postgres or DynamoDB |
| Supabase Auth | Cognito or custom JWT |
| FAISS (local) | OpenSearch or pgvector on RDS |
| Cloud Run | ECS Fargate or Lambda + API Gateway |
| Artifact Registry | ECR |
| GCP Secret Manager | AWS Secrets Manager |
| Vercel | CloudFront + S3 static hosting |

**Lesson:** Putting infra calls behind adapters from day one makes migrations surgical. Business logic never changes — only the adapter implementation and env vars change.
