# AI pipeline diagnostic, September 12

[Run 34700167991](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34700167991)
tested commit `e41ab5c2d5c2e73b462b5265c002bd6170e81c74`, synthesis v18,
and semantic judge v6. It covered four cases and seven turns. All four browser
journeys passed. Semantic results were two passes, one manual review, and one
infrastructure failure. This diagnostic does not establish release readiness.

| Case | Observed result | Remaining issue |
| --- | --- | --- |
| Graph expansion | Six original components and 12 edges preserved exactly; one component and two attachment edges added. New graph version rendered. Both final publications took less than 180 seconds. Semantic pass. | The component correction was needed for malformed generated prose. |
| Marketing | Published 20 components and 92 edges after correcting five contract gaps. | Final publication took 608 seconds. The diagram is crowded. The semantic judge stopped before calling its provider because its evidence exceeded 80,000 characters. |
| Memory | Recalled the same two mitigations on the follow-up. | Extra advice caused manual review. The one-paragraph request has an ambiguous scope; the extra recommendation is unrequested under either reading. |
| Long context | Retained EU residency, fewer than 10 requests per second, and manual approval before messages. Semantic pass. | Added an unnecessary missing-book-evidence note. |

The marketing correction added execution-time authorization and fencing checks,
exact-action compensation approvals, hostile evaluation cohorts, identity-scoped
reuse, and ingestion ordering/backpressure/replay contracts. Independent inspection
found those contracts in the published graph. A proposed graph does not demonstrate
that an implementation enforces them. The answer's categorical claim about
exactly-once support across unnamed ad platforms was not established by its evidence.

All 26 application attempts completed with usage. Application cost was $0.979786;
judge cost was $0.167992, totaling $1.147778. Three provider judgments completed;
the fourth budget reservation failed local preflight. No extra model calls were
made for the independent audit or the fixes below.

## Follow-up fixes

The judge encoded the final marketing graph twice: once under its conversation
turn and once as the final graph. Each copy occupied about 43,000 characters.
Judge v7 omits the top-level copy only when it equals the last captured turn graph.
Distinct final graphs and legacy captures retain their evidence. The 80,000-character
bound remains; graph fields and render identities are preserved. The retained
capture supplies an offline reproduction, without regenerating the graph.
Its judge payload is 69,091 characters after the fix, compared with 111,859 before.

Synthesis v19 omits the fake "no retrieved sections" context on empty retrieval.
Its evaluation packet records an empty string. Real passages and unavailable
requested web research retain their existing handling. This removes irrelevant
input; it does not prove that unsolicited caveats will disappear.

The browser runner now compares the saved final graph and version with the published
graph using its existing thread GET. Missing or mismatched content fails the case.
Only `view_state` is excluded because the layout writer may update it after publication.
The saved graph is retained separately in the capture for inspection.

These follow-up changes were not used by the live run above. Do not transfer its
results to the new prompt or judge release.

Offline validation passed 2,263 backend tests with 91% coverage and all 276
pipeline-policy tests. Two opt-in PostgreSQL tests skipped. Ruff, Bandit, dependency
audits, and manifest validation passed. Existing Starlette and LangChain dependency
deprecation warnings remain. All four retained cases fit the unchanged judge limit;
their answers and graph evidence reconstruct without mutation.

## Evidence limits and next work

The browser verified streamed graph content against rendered node and edge
identities. Its persistence check counted saved messages; the capture does not
independently establish that saved graph JSON equals the rendered graph.

The largest remaining production issue is the size and latency of the marketing
design. Internal gate approval and a rendered canvas do not resolve that issue.
Further simplification should reduce unnecessary component boundaries and contracts
while retaining required behavior. Avoid adding retries or widening deadlines to
hide the cost. Reuse captured evidence for evaluator work.

A complete release capture, actual human review, and judge calibration remain
outstanding. Production promotion and main merge have not occurred.
