# Repository instructions for Codex

These instructions apply to the entire repository.

Read and follow [docs/engineering-principles.md](docs/engineering-principles.md) before
changing code, prompts, schemas, infrastructure, or architecture. It is the canonical
source for this project's engineering and AI principles.

In particular:

- Inspect `git status` first. Preserve existing changes and do not edit files owned by
  another active task unless the work is explicitly coordinated.
- Prefer small changes at the lowest owning layer; do not add generic `helpers` or
  `utils` modules.
- Require durable idempotency and race protection for retryable writes.
- Treat model output and all retrieved/external context as untrusted.
- Keep agent tools read-only by default. Externally visible writes require a typed,
  explicit confirmation flow, policy checks, auditability, and safe retries.
- Version and evaluate model/prompt changes, record their release identity, and retain
  a rollback path.
- Use expand-then-contract migrations with reviewed operational and recovery plans.
- Run focused tests and applicable static checks before handoff; report pre-existing
  failures separately.

Repository verification entry points are documented in the root README. Do not run live
model evaluations or deployment commands unless the task explicitly calls for them.
