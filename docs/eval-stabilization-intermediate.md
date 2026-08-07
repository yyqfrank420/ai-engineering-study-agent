# Live Evaluation Stabilization: Intermediate Record

Last updated: 2026-08-06

This document records the work performed on draft PR #37 (`codex/critic-json-retry`), the evidence from protected and diagnostic evaluations, and the remaining production exit criteria. It is intentionally intermediate: production is not considered fixed until the exact approved tree is squash-merged and both Cloud Run and Vercel are verified on `main`.

## Objective and operating rules

- Make the protected eight-case live evaluation pass on the exact PR tree.
- Avoid repeating paid successful cases while debugging. Use `Scheduled evaluation` with `suite=diagnostic` and one unresolved case at a time.
- Run one final uninterrupted canonical eight-case evaluation only after targeted failures pass.
- Require free offline CI before any paid diagnostic.
- Cancel automatically triggered live workflows while a newly pushed head is not CI-verified.
- Publish/consume approval by Git tree identity so squash commits and synthetic PR merge refs cannot invalidate equivalent content.
- Squash-merge the final exact approved PR head.
- Verify the deployed Cloud Run backend and Vercel frontend after merge.

## Starting failure state

The most recent full protected run before targeted diagnostics was `31046260104` on head `ed2eab8`.

- Passed: `memory`, `research`, `prompt-injection`.
- `graph-off` reached manual review from a borderline semantic dimension.
- Failed graph-required cases: `rag-grounding`, `node-followup`, `graph-expansion`, `applied-domain`.
- All graph-required failures surfaced publicly as `graph_emitted=false`.
- Exact initial graph failures were output truncation, isolated nodes, oversized node/edge arrays, and an unknown endpoint.
- Deployment, WebSocket, browser capture, and frontend rendering were not the root cause.

The original provider boundary relied on array `maxItems`. Anthropic structured outputs do not support `maxItems`; the adapter removed that keyword, leaving count limits prompt-only.

## Major implementation changes

### Exact-tree evaluation and deployment provenance

- Added exact Git tree/content identity resolution for protected-evaluation approval.
- Reused approval across equivalent squash-merge and synthetic PR merge refs.
- Kept deployment tied to the tested immutable digest.
- Added/retained preflight behavior so unverified trees do not bypass the protected live gate.

### Applied graph generation

- Introduced a dedicated structured applied-graph boundary in `backend/agent/applied_graph_spec.py`.
- Replaced variable model-authored node IDs with exactly nine fixed slots (`n1` through `n9`).
- Replaced the large inlined grammar with shared internal `$defs` records.
- Retained a fixed nine-node object while representing cross-links with one compact array grammar.
- Limited accepted cross-links to the first ten valid, unique, priority-ordered links after self-loop/duplicate removal.
- Raised structured topology output capacity to 5,200 tokens within the existing 90-second graph-stage deadline.
- Added compact authoring limits for titles, labels, responsibilities, and link text.
- Required a connected parent backbone and converted it to the existing flat node/edge `GraphData` shape.
- Accepted forward parent references because slot order is identity, not semantic topology.
- Deterministically repaired extra roots, self-parenting, cycles, and depth overflow before the mandatory critic.
- Normalized provider-valid blank strings, enum casing, internal slot casing, and optional invalid cross-links.
- Added safe validation telemetry using field paths and categorical rules/actions without logging model-authored content.

### Mutation controls

- Kept `mutation_control` as enrichment metadata rather than publication proof.
- Cleared irrelevant role placeholders when `external_mutation=false`.
- Added deterministic global assignment of four distinct mutation roles when `external_mutation=true`, using fixed semantic/type scoring and stable slot tie-breaking while preserving valid supplied hints.
- Tightened compensation re-entry detection to require the selected authoritative-state source and validator target.
- Left the graph critic and deterministic publication contract as the authoritative safety gates.

### Focused graph repair

- Increased the bounded patch output allowance where required.
- Normalized authored add/update edge labels while keeping exact selectors immutable by default.
- Recovered a missing add-edge label only from an already-authored nonblank description.
- Added deterministic hard bounds for unbroken authored labels.
- Replaced prose-based edge selectors with immutable repair-only IDs assigned to the current graph for one patch call. Updates and removals now select `edge_1`, `edge_2`, and so on, including when several edges share endpoints. These IDs never enter published graph data.
- Applied one omission rule to blank/null update fields; an otherwise empty update still fails.
- Enriched added node and edge presentation fields through the same defaults as initial topology generation.
- Preserved the existing graph on invalid patches and retained critic/publication validation after every repair.

## Root-cause re-evaluation

The final `0f01d43` Cloud Run log records `edge label must be a bounded exact string` after the initial graph and critic completed. The immediate blank-label normalization in `4d7dcb3` covers that observed value. The previous selector recovery still left the protocol dependent on authored prose:

- The repair model had to reproduce source, target, and a natural-language label to identify an existing edge.
- Labels were also editable patch values, so identity and mutable content used the same fields.
- Endpoint-pair fallback could identify only graphs without parallel edges. Parallel approval, rejection, promotion, rollback, or reconciliation transitions are valid and common in this domain.
- Every new copy variation could expose another validation boundary even when the intended edge was clear.

The repair protocol now gives each existing edge a short immutable ID in the model's bounded patch context. The server resolves that ID against the unchanged input graph and applies authored changes separately. This removes the class of label copy, whitespace, truncation, and parallel-edge ambiguity failures instead of accepting more prose variants.

Diagnostic `31127543972` proved that selector identity was fixed and exposed a separate resource-contract defect. The patch call reported exactly 3,200 output tokens, took 38,885 ms, and the retained Cloud Run log recorded `model did not return a JSON object`. Adaptive reasoning exhausted the call's private 3,200-token hard cap before any complete patch object was emitted. The configured patch allowance was already 7,500 tokens, but the call applied a second lower cap in code. Its 40-second deadline also left no time to use the configured allowance.

The patch call now has one output-token owner, `GRAPH_PATCH_MAX_OUTPUT_TOKENS`, and a 90-second deadline. One design, initial review, repair, revision review, synthesis, and finalization reserve total 323 seconds, inside the 330-second terminal window. Later repairs remain subject to the existing remaining-time admission check. This change applies to every focused graph repair and contains no case text, edge labels, or expected topology.

Diagnostic `31127721414` confirmed that the resource correction worked. The first repair completed in 12,658 ms with 1,129 output tokens and produced a valid 20-edge candidate. A second critic identified two residual flow defects. The second repair returned in 2,819 ms, then failed strict publication with `edge technology cannot be empty`.

That failure exposed one broader patch-boundary inconsistency:

- The repair context omitted mutable node and edge technology and node descriptions.
- Update operations could carry blank placeholders even though no published graph field supports clearing to blank.
- An added edge was accepted initially with source, target, and label, while the final normalizer also required technology and description.
- Initial graph enrichment already owned deterministic technology and description defaults, but incremental additions did not use them.

The patch boundary now serializes every mutable node and edge field. It applies one omission rule to all blank/null update values and enriches every new node or edge with the same shared presentation defaults as initial topology generation. Strict reference, topology, semantic, and publication validation still run after this normalization. This is one provider-to-domain representation boundary rather than separate field-value exceptions.

### Research, citations, and latency

- Separated sourced facts from explicitly labeled inference in evaluation behavior.
- Preserved prompt-injection and research provenance protections.
- Bounded graph-repair work and raised the graph-design stage deadline to 90 seconds.
- Kept the overall terminal budget below the protected suite timeout while recording stage latency.

## Targeted diagnostic chronology

All runs below used the protected `staging-eval` environment, an ephemeral no-traffic Cloud Run revision, exactly one `rag-grounding` case, and no manual retry or replay. Automatically triggered unverified-head live workflows were canceled before staging/model execution.

| Run | Head | Result and newly exposed boundary | Application cost |
| --- | --- | --- | ---: |
| `31049959053` | `2fb98f8` | Anthropic rejected the inlined structured grammar as too large before generating graph tokens. | $0.220220 |
| `31051424417` | `a5f379d` | Shared grammar compiled; topology generation hit the 3,600-output-token ceiling. | $0.285888 |
| `31052310675` | `9d2c4c2` | Output completed; local validation rejected a forward parent reference. | $0.295519 |
| `31053207134` | `bd567c2` | Parent normalization worked; a provider-valid blank/casing difference reached opaque `graph_design_schema_invalid`. | $0.256938 |
| `31054260650` | `0003554` | Initial graph succeeded at 9 nodes/15 edges; critic requested clarity repair; patch failed on an invalid edge label. | $0.341419 |
| `31055260355` | `354be0f` | A stochastic initial response failed `mutation_control.semantic_roles` before critic. | $0.262750 |
| `31056353630` | `0f01d43` | Initial graph succeeded at 9 nodes/16 edges; critic repair again reached the remaining patch-label/selector boundary. | $0.332228 |
| `31127543972` | `f4c65e8` | Stable edge IDs reached the repair model; adaptive reasoning exhausted the hidden 3,200-token patch cap before a JSON object was emitted. | $0.328997 |
| `31127721414` | `2c1e507` | Resource limits worked and the first patch published; a second patch exposed incomplete mutable context and inconsistent add/update presentation-field handling. | $0.386551 |

Targeted diagnostic application spend recorded above: **$2.710510**. Semantic judge calls were not made because deterministic graph emission failed first.

The chronology is important: these were not repetitions of one identical defect. Each run cleared the previous boundary and exposed the next one. The main process failure was that the earlier full-suite workflow and coarse `graph_emitted=false` telemetry made this dependency chain expensive to discover.

## Current checkpoint

Repair-ID implementation commit: `f3b6659`. Root-cause record commit: `f4c65e8`.

Current implementation state:

- Immutable repair-only edge IDs replace prose selectors and endpoint-pair recovery.
- The focused repair call uses its configured 7,500-token allowance and a 90-second deadline.
- Patch context includes every mutable field; additions share initial-topology presentation enrichment; updates use one blank/null omission rule.
- Regression coverage includes exact selection among parallel edges, unknown IDs, complete mutable context, shared addition defaults, update omission semantics, authored label normalization, and patch prompt identity.
- The complete patch-boundary correction passed the full local offline gate and awaits one targeted diagnostic.

Most recent authoritative evidence:

- Offline CI `31085357395`: success on `4d7dcb3` before the repair-ID change.
- Diagnostic `31056353630`: initial graph and critic both executed; failure is isolated to focused repair validation.
- Diagnostic `31127543972`: edge IDs were accepted; the patch call hit exactly 3,200 output tokens and the server preserved the existing graph because no JSON object was emitted.
- Diagnostic `31127721414`: the first repair published a valid candidate; the second repair failed because the patch protocol omitted and inconsistently required presentation fields.
- Focused local patch/spec/graph/critic/workflow verification after the complete boundary correction: 209 tests passed.
- The exact working tree passed the full local offline gate under the CI Node 20 runtime. This covered all backend groups, 141 frontend tests and build, static/security, ingestion, migrations, Terraform validation, policy checks, and the production container build.
- Backend/frontend staging readiness, dashboard smoke, capture, cleanup, artifact upload, latency accounting, and cost accounting all passed.
- Production remains on stale `main`; no production-success claim is made.

## Evaluation workflow lessons

1. Provider-supported JSON Schema is smaller than general JSON Schema. Unsupported cardinality keywords cannot be treated as enforcement.
2. A schema can be valid but too expensive for the provider grammar compiler. Repeated optional properties and divergent enums multiply grammar complexity.
3. Structured output guarantees shape better than semantics. Empty strings, enum casing drift, and normal `end_turn` responses still require a provider-to-domain normalization boundary.
4. Fixed identifiers are useful, but numeric slot order must not be confused with dependency order.
5. Deterministic normalization should repair representation, not certify semantics. The independent critic and publication validator remain mandatory.
6. Patch selectors and authored values need different representations. A short repair-only ID preserves identity without asking a model to copy mutable prose or assuming endpoint pairs are unique.
7. Preserve safe telemetry at every boundary: finish reason, response size, validation path/rule, normalization action, operation stage, and match count. Do not log prompts or authored content.
8. A public `graph_emitted=false` code is insufficient for operations. It hid grammar compilation, truncation, topology, mutation-role, critic, and patch failures behind one predicate.
9. Diagnostic cases are appropriate for iterative debugging, but they cannot publish an `approved-tree-*` tag. Final approval still requires one canonical complete eight-case run.
10. Exact-tree identity is required for safe approval reuse across squash merges; commit SHA equality alone is insufficient.

## Remaining execution order

1. Pass required GitHub offline CI on the exact repair-ID tree.
2. Rerun only `rag-grounding`.
3. If it passes, run only `node-followup`.
4. If it passes, run only `graph-expansion`.
5. Run `applied-domain` separately because its diagnostic provenance rules require a standalone successful dispatch for override evidence.
6. Address `graph-off` only if a current targeted or final run still returns manual review.
7. Run one uninterrupted canonical eight-case protected evaluation on the final exact tree.
8. Verify the exact-tree approval tag and required PR checks.
9. Mark PR #37 ready and squash-merge with the exact final head guard.
10. Monitor the `main` production workflow through immutable backend deployment, smoke/promotion, and Vercel deployment.
11. Verify Cloud Run revision/digest/traffic and the public backend and Vercel frontend URLs.

## Repository and contributor notes

- The README has been updated during this stabilization branch.
- GitHub collaborator inspection did not show Claude as an active repository collaborator. The screenshot entry is contributor/history attribution, which is not removed by collaborator permissions.
- `Agent-eval-research-security` and `Agent-live-eval-parallel` were branch/worktree names used during evaluation work, not live production services.

## Completion definition

This effort is complete only when all of the following are true on authoritative current evidence:

- Exact final PR head has required offline CI success.
- Targeted unresolved cases pass.
- One final canonical eight-case protected evaluation passes without manual review or infrastructure failure.
- The exact Git tree has a valid protected-evaluation approval.
- PR #37 is squash-merged, not merge-committed or rebased into multiple production commits.
- `main` deployment completes for the tested tree/digest.
- Cloud Run serves the promoted revision and passes public health/smoke checks.
- Vercel serves the current frontend deployment at the production alias.
