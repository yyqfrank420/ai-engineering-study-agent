# Repository instructions for Claude Code

These instructions apply throughout this repository.

The authoritative engineering and AI standard is
[docs/engineering-principles.md](docs/engineering-principles.md). Read it before making
changes; do not maintain a separate interpretation in this file.

Always inspect the worktree before editing and preserve changes belonging to other active
work. Make the smallest coherent change at the owning layer. Pay particular attention to
durable idempotency, database race protection, canonical persistent data, safe migrations,
untrusted model/context boundaries, prompt/model regression evidence, and explicit
confirmation for any externally visible write.

Do not run live model evaluations, deploy, mutate production data, or apply production
migrations unless the task explicitly requires that action. Run focused tests and relevant
static checks locally, and distinguish new failures from pre-existing concurrent work.
