# Live Evaluation Stabilization: Intermediate Record

Last updated: 2026-08-12

Evidence in this record is current through paid diagnostic `31616927365` on exact head
`5c9b27589a29aef90d77571f993a37ab089fa6ce`
on 2026-08-12. PRs #37 through #40 merged on 2026-08-07, and PR #44 merged as `77df25e7`. The
evidence-provenance, graph-review, and latency corrections have passed local review and the full
offline CI matrix. Twelve consecutive recent `graph-expansion` diagnostics have failed; there is no
protected live success on the current branch. The latest paid run retained a valid ten-node,
thirteen-edge graph and passed private rendering, then failed protocol validation during semantic
review. Its final authoritative `graph_data` was `null`. The correction adds typed coordinates for
root scorecard shape errors, preserves nested contract coordinates, and treats failure of the
server-canonical review as a server invariant without a model retry. It has not yet been proven by a
live run. One exact `graph-expansion` retry is authorized. Corpus `2026-08-12.v1` remains pending
human review.

## Objective and operating rules

- Make the protected eight-case live evaluation pass on the exact PR tree.
- Avoid repeating paid successful cases while debugging. Use `Scheduled evaluation` with `suite=diagnostic` and one unresolved case at a time.
- Run one final uninterrupted canonical eight-case evaluation only after targeted failures pass.
- Require free offline CI before any paid diagnostic.
- Cancel automatically triggered live workflows while a newly pushed head is not CI-verified.
- Publish/consume approval by Git tree identity so squash commits and synthetic PR merge refs cannot invalidate equivalent content.
- Preserve PR #37's two reviewed commits and merge the focused contract correction.
- Verify the deployed Cloud Run backend and Vercel frontend after merge.

## Recent diagnostic failure ledger

This is the canonical chronology for recent `graph-expansion` failures through
`5c9b27589a29aef90d77571f993a37ab089fa6ce`. Every
row records a live product failure. A green workflow conclusion for a report-only row means the
pending-corpus workflow uploaded its evidence and exited without enforcing the failed verdict. The
initial workflow runs failed; later report-only diagnostics concluded green under that policy.
The retained `live-results.json` for every row says `status: fail`. All twelve failures ended on turn
1 and skipped turn 2. The latest two emitted a reversible preview but no authoritative graph; the
preceding ten emitted no visible graph.
Run links and exact heads come from GitHub Actions metadata. Latency, provider calls, failure codes,
and cost come from each retained `scheduled-eval-<run>/browser-results.json`, `live-results.json`,
and `run-context.json` artifact. Model effort comes from source at the exact run head because the
older telemetry did not store effort. Minimum cost is used whenever an accepted provider call has
incomplete usage.

| UTC start | Run and exact head | Observed live failure | Current correction status | Application cost |
| --- | --- | --- | --- | ---: |
| 2026-08-09 19:59 | [`31333075986`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31333075986), `2f88a5a` | Opus produced a plan in 121.554 seconds. An aggregate plan-size rejection returned `architecture_pass_invalid`, entered a two-node fallback, and ended with an unauthorized whole-fallback patch. Five calls ran; turn latency was 265.956 seconds. | Removed the aggregate size cap, added structural failure codes, made a missing plan fail closed, and enforced exact repair scope. | $0.435752 |
| 2026-08-09 20:53 | [`31335429802`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31335429802), `b2bd76a` | Architecture failed `architecture_pass_evidence_provenance` after a 139.767-second, 9,931-token plan. Human-readable references could not identify one exact source. Two calls ran; turn latency was 168.228 seconds. | Added canonical source identity and exact evidence validation. The corpus now requests the monitoring component in turn 1. | $0.353252 |
| 2026-08-09 22:40 | [`31340006983`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31340006983), `7ce69b6` | The `xhigh` Opus architect exhausted its 150-second role deadline after 149.813 seconds with no final output. Two calls ran; turn latency was 178.296 seconds. | Reduced architect effort. Later live evidence rejected `low`, so the current prototype architect uses `medium`. | at least $0.067810 |
| 2026-08-10 08:16 | [`31369358742`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31369358742), `77df25e7` | The architect completed in 111.877 seconds, then evidence validation rejected a model-copied 69-character source hash at `evidence_basis[2].evidence_ref`. Two logical calls used three provider attempts; turn latency was 153.688 seconds. | Models now receive request-scoped slots such as `source_1`; the server resolves them to canonical source IDs. | $0.300365 |
| 2026-08-11 18:38 | [`31523789373`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31523789373), `9a3dcd2` | A seven-call serial path ran architect, challenger, topology, review, patch, post-patch review, and synthesis. The path withheld the graph after 370.581 seconds. | Removed the challenger from graph publication, bounded review and repair rounds, added dependency-aware layer locks, and added a reversible preview after deterministic render validation. | $0.607108 |
| 2026-08-11 23:46 | [`31547774792`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31547774792), `67887c3` | Private render passed at 127.374 seconds. Sonnet then emitted an over-broad composition contract, rejected at `layers.composition.group_ids: unbounded_collection`; the 180-second deadline cancelled correction before any visible preview. Four calls ran; turn latency was 180.122 seconds. | Prototype-only subjective findings are advisory, repair authority is record-bounded, invalid contracts receive one typed correction, and deterministic render success emits a reversible preview. | at least $0.276605 |
| 2026-08-12 00:08 | [`31549117335`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31549117335), `1a279b6` | The `low`-effort architect violated a hard plan-list limit. The server returned `architecture_pass_list_limit`; Kimi and Sonnet did not run. Two Opus calls ran; turn latency was 88.836 seconds. | Restored prototype architecture to `medium`, which had produced a valid plan in the preceding diagnostic. | $0.201845 |
| 2026-08-12 00:16 | [`31549644038`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31549644038), `b64f66f` | A valid architect plan took 78.784 seconds and Kimi took 81.252 seconds. Deterministic topology validation rejected `connections.links[6]` before private render, preview, or Sonnet. Three calls ran; turn latency reached 180.083 seconds. | The topology boundary accepts a uniformly one-based link array only when the entire array is invalid as zero-based and valid as one-based. Retained evidence cannot prove this run used one-based indexes, so this correction still needs live verification. | at least $0.232051 |
| 2026-08-12 10:46 | [`31588931923`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31588931923), `ca8e3b2` | The architecture boundary rejected `evidence_basis[8].evidence_ref` under the private rule `invalid_engineering_area`. Two calls ran; the turn took 107.735 seconds and the case took 109.568 seconds. No Kimi, private render, critic, turn 2, or fallback ran. | Removed engineering recommendations from model-facing evidence. Checklist guidance now belongs in decisions or assumptions, and legacy model rows are discarded without weakening book, web, or user provenance. The green wrapper was report-only; the correction is not live-proven. | $0.236575 |
| 2026-08-12 15:24 | [`31612168038`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31612168038), `ad82144` | Kimi low returned a complete topology in 24.530 seconds on one attempt. Deterministic validation rejected `composition.steps[3][0]` because the model's sequence order conflicted with its directed tree. No preview, render, architecture review, semantic review, or turn 2 ran. Fallback synthesis completed after rejection. The case took 61.025 seconds. | Sequence batches now select membership only. The server derives stages by breadth-first traversal from the root across selected tree and runtime edges. Missing-root, duplicate, invalid, and unreachable selections still fail closed. | $0.082805 |
| 2026-08-12 15:51 | [`31614596529`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31614596529), `5a3b5f1` | Kimi low produced a valid seven-node graph. Topology validation and private rendering passed, and the reversible preview appeared after 37.228 seconds. Initial Sonnet review and its one protocol correction both returned successfully, but the corrected canonical contract retained `group_ids` without authorized `groups` authority. Review failed at `layers.composition.group_ids: invalid_contract`; the preview was withdrawn, turn 2 was skipped, and the case ended after 289.826 seconds. Five calls ran without provider fallback. | Canonicalization now filters group IDs, sequence indexes, assumption indexes, and their append counts through the server-authorized composition fields as one atomic permission profile. | $0.426546 |
| 2026-08-12 | [`31616927365`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31616927365), `5c9b27589a29aef90d77571f993a37ab089fa6ce` | The run retained a ten-node, thirteen-edge graph and emitted a reversible preview after 24.116 seconds. Private rendering passed, but semantic review failed with `semantic_review_protocol_invalid` at correction `critic_scorecard: invalid_contract`. Final `graph_data` was `null`; turn 2 was skipped. Five application calls ran without fallback. The turn took 263.485 seconds and the case took 265.625 seconds. | Preflight now checks the exact root scorecard shape and emits `critic_scorecard: invalid_shape`. Nested contract defects retain their leaf coordinates. A failed server-canonical invariant emits `canonical_review: invalid_server_state` and skips model correction. | $0.457343 |

Known application spend across these twelve failures is at least **$3.678057**. Several provider
calls have incomplete usage; row amounts marked `at least` are lower bounds. Diagnostic
`31549644038` retained only `connections.links[6]: topology`; it did not retain authored output and
cannot distinguish an out-of-range endpoint from a self-link.

Head `fdd70d1` passed all 11 jobs in [offline CI
`31552299595`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31552299595).
Its [live-gate workflow
`31552299591`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31552299591)
skipped protected staging and model execution because the corpus is pending review. This proves the
offline tree and gate policy. It supplies no live graph or latency evidence for `fdd70d1`.

Recent branch CI had no genuine offline failure. Automatic live-gate runs `31333067244` and
`31335165144` were cancelled before protected browser or model execution while their new heads were
unverified. Scheduled `main` runs `31354658015` and `31456923829` were also cancelled with no steps
or logs before manual diagnostics entered the global staging queue. These cancellations are excluded
from the product-failure ledger.

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

This subsection records the fixed-slot contract used by the earlier stabilization branch. The current
runtime supersedes it with variable arrays, model-authored groups and sequence membership, strict
reference and cycle validation, and resource-safety ceilings that are absent from model prompts. It never truncates
cross-links, reparents invalid topology, or deletes authored elements to fit a target count.

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

### Topology authority

- Removed the unused `mutation_control` side channel and its heuristic role assignment.
- Stopped server code from inventing compensation and rollback edges from inferred topology.
- Kept safety controls in one representation: authored nodes and edges reviewed by the deterministic and semantic publication gates.
- Reduced the structured-output grammar and removed the prior `mutation_control.semantic_roles` failure boundary.

### Focused graph repair

- Increased the bounded patch output allowance where required.
- Normalized authored add/update edge labels while keeping exact selectors immutable by default.
- Recovered a missing add-edge label only from an already-authored nonblank description.
- Added deterministic hard bounds for unbroken authored labels.
- Replaced prose-based edge selectors with immutable repair-only IDs assigned to the current graph for one patch call. Updates and removals now select `edge_1`, `edge_2`, and so on, including when several edges share endpoints. These IDs never enter published graph data.
- Applied one omission rule to blank/null update fields; an otherwise empty update still fails.
- Enriched added node and edge presentation fields through the same defaults as initial topology generation.
- Preserved the existing graph on invalid patches and retained critic/publication validation after every repair.

### One-shot architecture product and model roles

Historical, superseded repair-limit description:

The product target is a one-shot, publishable architecture diagram. Opus 5 xhigh writes the primary
architecture brief, then performs a clean second-pass review before graph construction. Kimi K3 low
owns initial graph topology. Kimi K3 high applies one typed local repair to a rejected unpublished
candidate and handles user refinements to a previously published graph. Sonnet 5 medium reviews architecture
semantics and the private browser screenshot before publication. The protected semantic judge also
defaults to Sonnet 5 high.

The historical workflow permitted up to three bounded local repairs after the first candidate. Each review
selects one connected repair region and sees the full current graph again. A failed QA result after
the third repair suppresses the graph. Normal operation should publish the first candidate; repair rate and first-pass acceptance
are release metrics, not an authoring strategy.

Each reasoning role has a completion budget separate from the visible artifact bounds. Opus xhigh
receives 16,000 completion tokens for its bounded JSON plan. Kimi low topology generation and Kimi
high focused repair each receive 65,536. Sonnet graph QA receives 16,384. The two Opus passes each own
up to 150 seconds within the shared request deadline. Initial Kimi construction and Kimi repair each
own up to 150 seconds. Sonnet graph review owns 90 seconds and can borrow unused upstream time up to
180 seconds while downstream reserves remain intact.
Protected runs measured both 89-second and 119-second Kimi max calls with accepted private reasoning
and no structured output. A production-sized high probe also exhausted 120 seconds, so the initial
topology uses low effort for schema translation after Opus has made the design decisions. The
repeat production-sized low probe completed a valid 25-node, 33-edge topology in 74.67 seconds
with 3,215 completion tokens. The complete one-repair path retains 37 seconds of request-deadline
reserve.
Graph nodes and edges have high resource-safety ceilings for rendering and persistence. The ceilings
stay out of prompts and never shape a valid design. Text and patch payloads retain transport bounds. This avoids
the earlier failure where hidden reasoning exhausted a small JSON-output cap before a complete object
appeared.

Kimi uses one OpenAI-compatible adapter boundary with strict structured output, streamed reasoning,
bounded pre-output retry, provider usage telemetry, and automatic-cache accounting. The production
topology schema inlines its two strict record shapes because K3's documented schema subset does not
guarantee `$ref`. The browser still renders every candidate off-screen. Deterministic geometry checks
 run first, then Sonnet receives the private screenshot and layout report for visual hierarchy and
semantic QA.

The root-cause review removed the fixed nine-node schema, positional three-group and five-step
fabrication, cap-plus-one node and edge deletion, silent reparenting, first-draft ID retention, partial
critic feedback, lexical semantic overrides, and the 520 ms screenshot timer. The renderer now signals
layout readiness. Missing or failed browser evidence rejects the candidate. Sonnet's explicit rejection
cannot be reversed by local label matching.

The later graph-expansion diagnostic exposed a separate state identity failure after a strong first
candidate. The workflow created and rendered a complete 33-node, 53-edge graph. Critic provider work
completed, but protocol postprocessing raised `ValueError`, so the unpublished candidate was withheld.
The second turn then generated an unrelated canonical fallback with 10 nodes and 3 edges. Evaluation
flattened evidence across turns and accepted matching counts instead of the exact per-turn graph
identity. The semantic judge ran in report-only mode. Ten eager node-detail calls added cost without
contributing to the result.

This changed the working diagnosis. Model intelligence and graph size were not the active failure.
The graph lifecycle allowed candidate identity to be lost between creation, review, repair, rendering,
and evaluation. A local protocol error could discard a near-complete artifact, and a later unrelated
artifact could satisfy the coarse final predicate.

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

The canonical eight-case run `31161384348` on the rewritten two-commit branch exposed five shared contract conflicts after the earlier patch-boundary work:

- Graph generation admitted edge labels up to 100 characters while repair pre-validation rejected unchanged labels above 80. The failed RAG candidate contained an 87-character valid label.
- Server enrichment synthesized a 98-character compensation edge from heuristic role assignments. The same inferred route was semantically wrong in the model-serving candidate.
- The repair layer rejected a 14-operation candidate before final node, edge, structural, and semantic validation, even though those lower gates already bound the resulting graph.
- A structurally valid initial graph was rejected by deterministic semantic checks inside generation, before the canonical critic could return focused repair feedback.
- Repair admission required the full 90-second timeout allowance rather than using the available bounded interval after reserving critic, synthesis, and finalization time.

The correction removes the unused role side channel and synthesized edges, gives edge labels one 100-character owner, removes the redundant aggregate patch-operation cap, routes structurally valid drafts through the canonical critic, and treats stage timeouts as caps. The final topology and publication validators remain unchanged.

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

## Current graph-review convergence checkpoint

This state machine supersedes the historical repair limits and layer-lock descriptions below.
Focused offline tests cover its contracts. Diagnostic `31333075986` exercised this state on the
protected `graph-expansion` case and exposed the architect-boundary failure recorded below.
This checkpoint described the former Opus-first stabilization path. The preview-first state machine
recorded in the 2026-08-12 latency section supersedes its generation order while retaining the same
review, repair, layer-lock, and publication contracts.

- Every initial candidate receives one exhaustive component, connection, composition, and render
  scorecard. Every deterministic finding is classified exactly once. `novice_clarity` is advisory:
  it may guide presentation improvements but cannot reject a candidate or create repair authority.
- The selected review depth is authoritative. Prototype review rejects production-only findings even
  when request text describes a production system. Production review retains all topology proofs.
- Repair patches are record-scoped and may cover non-adjacent records in the same connected
  candidate. Every cited node, edge, group, sequence, assumption, field, removal, and addition has
  its own exact permission; topology proximity grants none. Each required connection addition names
  its exact directed `source -> destination` obligation. A group move requires permission for both
  source and destination groups.
- `authored_composition` uses a server-owned title, groups, and sequence repair profile. The profile
  grants only the selected indexed or append permissions required by the failed contract; critic and
  patch output cannot widen it.
- Retained pass verdicts follow dependency invalidation. Component changes reopen components,
  connections, and composition. Edge changes reopen connections and composition. Composition-only
  changes reopen composition.
- The workflow retains the reviewed graph snapshot beside its scorecard as the repair baseline; a
  later scorecard cannot be paired with a different graph version.
- It permits at most two successful semantic repair rounds and one error-informed critic-contract
  correction. An invalid local admission preserves the current candidate, returns its safe typed
  validation path and rule to one fresh critic correction, and consumes that correction budget. The
  corrected Kimi prompt cannot repeat the rejected prompt. Each post-patch review classifies every
  prior server-issued typed blocker as resolved or still failing. The same semantic blocker may use
  the second repair only when the new scorecard supplies a different exact repair fingerprint. The
  same blocker with the same mutation authority fails closed without another Kimi call.
- A request-scoped budget caps Sonnet critic provider calls at four across initial review, one shared
  protocol or contract correction, and two post-patch reviews. The same budget object survives
  WebSocket steering restarts, and reaching either ceiling fails closed before provider dispatch.
- Layer locks retain the selected review depth with the scorecard. Moving from prototype to
  production reopens connections and composition and requires fresh production topology proofs.
- A local contract may combine exact component or connection changes with the title and selected
  assumption records that those semantic changes require. Assumption edits use exact indexed or
  append permissions; unrelated composition records remain locked.
- A broad expansion resolves one existing component against the approved graph and authorizes one
  directly connected child plus any required group placement. Zero or multiple target matches
  preserve the approved graph for clarification. The edit lane never rebuilds the graph.
- Publication states are explicit: `approved` emits the reviewed accepted graph, `preserved` keeps
  the prior approved graph after a rejected edit without emitting stale candidate `graph_data`, and
  `withheld` emits no unapproved create candidate. An edit cannot fall back to graph creation.
- Every candidate receives deterministic render validation.
- Publication requires a final merged full-graph pass.

### Detailed analysis for runs 31333075986 through 31340006983

The recent diagnostic failure ledger above is the canonical status and chronology. This section
retains the longer root-cause record for the first three runs in that sequence.

Diagnostic `31340006983` ran only `graph-expansion` on exact head `7ce69b6`. The Opus architect
exhausted its 150-second role deadline at `xhigh` effort. Its accepted provider attempt ran for
149.813 seconds with zero final output and no queue wait. The browser turn failed after 178.296
seconds with no `graph_data`, private render, fallback, Kimi, Sonnet, repair, or second turn. The
workflow conclusion was green only because a pending corpus makes diagnostic verdicts report-only.
The architect now uses `high` effort. Its model, structured contract, graph critic, and fail-closed
timeout remain unchanged. The graph workflow no longer invokes the challenger. This correction
passed the full offline matrix and needs a freshly authorized diagnostic before merge.

Diagnostic `31335429802` ran only `graph-expansion`. It failed with
`architecture_pass_evidence_provenance` after 170.265 seconds for the case and 168.228 seconds for
the turn. It made two application calls, no judge calls, and cost $0.353252. The architect call took
139.767 seconds and emitted 9,931 output tokens. Synthesis took 25.602 seconds. No graph was
constructed or privately rendered. No fallback, Kimi, Sonnet, repair, or second corpus turn ran.

The root defect was evidence ambiguity at the architecture boundary. The plan could use
human-readable book or web references whose identity and basis could not be verified as one exact
source record. The run also exposed a corpus precondition defect: the first `graph-expansion` prompt
did not explicitly require the monitoring component that the second prompt asked to expand.

The current recovery gives each bounded book and web source record an opaque hashed ID and
requires that exact ID for book and web evidence references. Rejected provenance now reports only a
safe evidence path and rule. The revised first corpus prompt explicitly requests a monitoring
component. Its second prompt requests exactly one directly connected responsibility. The corpus is
`2026-08-12.v1` and remains pending a fresh full protected capture, human review, judge calibration,
and an approved manifest hash. No live success follows from these changes, and no further paid run is
authorized.

Diagnostic `31333075986` ran only `graph-expansion` on exact head `2f88a5a`. The first turn failed
after 267.912 seconds with no published graph. Five application calls cost $0.435752 and no judge
call ran. Opus planning took 121.554 seconds, then local plan validation returned the generic
`architecture_pass_invalid` code. The graph worker replaced the missing plan with a two-node
prototype fallback. Sonnet used one protocol correction for an invalid connection-addition row.
Kimi then spent 92.203 seconds on a patch that updated every node in the fallback, which the blanket
incremental-identity guard rejected. The second corpus turn did not run.

The recovery removes the aggregate 12,000-character plan rejection because its field schema permits
larger valid plans and the provider call already has a token ceiling. Architect failures now expose
stable structural codes. A missing architecture plan fails closed instead of entering a canonical or
generic fallback. Exact critic permissions may update every cited record in a small graph, while
unscoped whole-graph rewrites remain rejected. Critic and patch prompts now define non-adjacent repair
authority, two-node addition endpoints, group-move permissions, and semantic ownership without the
ambiguous disconnected-region wording.

Offline coverage exercises these boundaries. The next paid `graph-expansion` diagnostic requires
fresh authorization. Do not run it as an automatic retry or include this corpus revision in the
canonical evaluation before its full capture, human review, calibration, and manifest hash complete.

## Historical stabilization checkpoint

PR #37 preserved `87c9012` and `cbbc892` as its two reviewed commits. The post-merge contract correction is isolated in one follow-up commit.

Implementation state at that historical checkpoint:

- Immutable repair-only edge IDs replace prose selectors and endpoint-pair recovery.
- Initial topology and one typed local repair each use the 65,536-token safety ceiling and a
  150-second deadline. The same typed patch boundary handles published graph refinements.
- Sonnet returns one schema-constrained review with separate component, connection, composition,
  and render assessments. Five named topology proofs cover disjoint cross-layer guarantees. The
  provider response uses compact positional rows under those fixed names. The server restores named
  fields, expands numbered rubric codes and indexes, and validates the canonical repair contract.
  Failed component and connection rows state exact addition counts and read-only context nodes.
  Composition rows state exact append counts for groups, sequence, and assumptions. A local repair
  can change only cited failed records. Passing layers and uncited records remain locked
  before the patch and after normalization. Read-only obligation and node-anchor indexes make
  missing-record repairs specific without granting mutation rights. A graph-caused render failure
  may share one local repair with a failed editable layer. Render-only and global failures suppress
  the diagram.
- The four score layers have one server-owned partition of mutable fields. Components owns node
  records. Connections owns edge records. Composition owns title, groups, sequence, and assumptions.
  Render owns the measured screenshot and layout. Each rubric code and deterministic finding has
  exactly one owner. A defect that needs changes in two layers must fail both owners.
- Historical, superseded layer-lock design: a passing layer is retained across one bounded repair when its full dependency fingerprint is
  unchanged. Component locks cover every mutable node field. Connection locks cover every mutable
  node and edge field because endpoint meaning can change without an edge rewrite. Composition locks
  cover its records and every semantic node and edge field. Render locks cover the full graph.
  A current deterministic finding prevents a stale pass from being restored. The corrected scorecard
  and topology proofs are validated again after locks are applied.
- Graph operations carry typed create or edit state and candidate, applied, or failed state. An edit
  cannot enter canonical fallback. A failed or ineffective local patch preserves the last applied
  graph and ends that repair attempt.
- User edits and critic repairs apply typed patches to exact records. Connection endpoint names are
  read-only anchors. Added edges are limited to new node IDs plus those named anchors. Unspecified
  fields fail before the patch call. New component IDs, connection endpoints, removal targets, and
  composition append counts come from the edit scope. Normalization rechecks every field that the
  scope did not permit.
- Connection additions require at least two declared endpoint identities. Component additions in a
  grouped graph either update one named existing group or append exactly one declared group. A zero
  append budget rejects new group, sequence, and assumption records.
- Browser evidence is turn-scoped. Each graph-required turn must produce a fresh graph version and
  exact node and edge identities in the D3 DOM. Matching counts cannot substitute for matching
  records. The final deterministic gate applies the same identity check to auto-graph cases. The
  semantic judge receives each turn's graph, rendered identities, and turn-tagged retrieval and
  research evidence, so it can evaluate preservation across an edit.
- Node details are generated only after an explicit selection. Graph publication no longer triggers
  eager detail calls for every node.
- Patch context includes every node and edge as a compact global skeleton. Only selected records,
  named context nodes, selected edges, and editable composition collections include full mutable
  detail. Original repair-only edge IDs stay stable across the projection. Failed rubric and topology
  proof names receive compact server-owned acceptance criteria; unrelated rubric text is omitted.
- The private evaluator owns one fixed 1440x960 publication frame. Deep graphs keep whole topology
  levels and use deterministic alternating tracks. Skip, wrap, and return edges use row and track
  gutters. The deterministic publication gate requires node titles of at least 11 pixels.
- Regression coverage includes exact selection among parallel edges, unknown IDs, complete mutable context, shared addition defaults, update omission semantics, the 100-character label contract, larger bounded patches, partial repair windows, authored-only topology, and patch prompt identity.
- At this historical checkpoint, the stabilization tree passed 1,034 tracked backend tests at 90%
  total coverage. The frontend passed 214 tests with 91.32% statements, 79.02% branches, 93.33%
  functions, and 93.64% lines. Static analysis, dependency audits, ingestion artifacts, migrations,
  Terraform validation, the production frontend build, and the backend container build passed on
  that working tree.

Historical checkpoint evidence:

- Diagnostic `31226616907` reached the private browser render, then Anthropic rejected the repeated
  four-layer Sonnet review schema with HTTP 400. A one-token replay captured the provider message:
  `The compiled grammar is too large`. The replacement provider contract defines one tagged layer
  assessment array and converts it to the existing four-key domain map before validation. The exact
  replacement schema compiled successfully in a one-token Sonnet 5 replay. The diagnostic was
  cancelled before its second architecture chain could repeat the same deterministic failure.
- Diagnostic `31227838552` proved the replacement critic schema no longer blocks graph work. Its
  Opus architect and challenger completed in 108.6 and 118.0 seconds. Kimi then streamed 18,680
  topology characters and hit the former fixed 150-second design limit before response completion.
  The run was cancelled before its follow-up could repeat the failed first turn. Design and patch
  now retain their 150-second guaranteed reservations and may borrow unused upstream time up to 240
  seconds. Admission still reserves both Sonnet reviews, one repair, synthesis, finalization, and
  30 seconds for workflow orchestration.
- Diagnostic `31229001829` confirmed that Kimi completes when it can borrow saved upstream time. It
  returned 27,205 topology characters in 159.3 seconds on one attempt. The first Sonnet review then
  reached its former fixed 90-second limit after 88.5 seconds inside the provider call and returned
  no structured assessment. Critic calls now retain their 90-second guaranteed reservation and may
  borrow saved time up to a 180-second liveness ceiling under the same downstream and orchestration
  reserves. Safe availability, about 164 seconds in this run, remains the active limit when lower.
  The run was cancelled after its second architect call to avoid paying for a graph that could not
  satisfy the already-failed first-turn expectation.
- Diagnostic `31230128866` confirmed that the remaining failure sits at the Kimi topology wire
  boundary. Opus architect and challenger calls completed in 108.1 and 112.8 seconds. Kimi streamed
  23,815 visible JSON characters for 234.4 seconds and consumed the full safe window reserved around
  the two critic calls, one patch, synthesis, finalization, and orchestration. Current evidence does
  not support reducing a downstream deadline. The topology wire contract now owns three disjoint
  graph sections: components, connections, and composition. Render evidence remains a fourth critic
  layer. Components, tree edges, non-tree links, groups, and sequence steps use compact positional
  references. Server validation restores the same canonical graph and checks fixed tuple arity, enum
  values, exact group partitioning, rooted acyclic topology, unique links, and sequence references.
  This removes repeated field names and duplicated prompt commitments without changing critic,
  repair, renderer, or publication behavior.
- A one-token Kimi K3 probe accepted the exact v9 production schema. It opened the structured stream
  and was closed after the first event. No graph generation was requested.
- Diagnostic `31232163789` proved the compact wire removed the topology timeout. Kimi returned a
  complete 15,510-character object in 135.8 seconds on one attempt, compared with 23,815 characters
  and 234.4 seconds in `31230128866`. Server validation then rejected `components[0][1]` because the
  positional schema could no longer enforce a distinct node-type enum and the v9 prompt omitted the
  allowed vocabulary. The run was cancelled after the next architect call and before a second Kimi
  call. V10 uses disjoint integer namespaces generated from the validator's canonical mappings:
  node type `100-108`, tier `200-201`, lane `300-301`, flow `400-403`, sync `500-501`, and group kind
  `600-604`. Every categorical position rejects foreign, malformed, and unknown codes. The canonical
  graph still contains the same named values. A one-token Kimi probe accepted the exact v10 schema.
- Diagnostic `31233156283` proved Kimi v10 could build and render the first private candidate: 35
  nodes, 57 edges, and 5 groups completed in 99.3 seconds. Sonnet then spent the full 16,384-token
  completion allowance on adaptive thinking and emitted no scorecard after 174.4 seconds. The
  workflow failed closed as `semantic_review_output_truncated`. A later Kimi response also exposed
  that separate component and tree arrays could drift in count.
- V11 makes component/tree drift unrepresentable. The root row and each parent-before-child
  component row carry their incoming tree edge in one record; non-tree links remain separate. Every
  rooted tree is representable through a parent-first ordering, and the server still validates the
  restored canonical graph.
- Critic v30 keeps the 16,384-token cost ceiling, uses Sonnet medium effort, and replaces repeated
  free-form review prose with four fixed named layer scorecards and five fixed named topology
  proofs. Rubric codes and bounded indexes are expanded server-side into exact selectors and repair
  context. Pass status requires a score of at least 0.78; fail status requires a lower score.
- Diagnostic `31235230016` proved Kimi v11 completed the first graph on the exact `2abf303` tree.
  Opus architect and challenger completed in 103.3 and 119.8 seconds. Kimi returned 12,414 topology
  characters in 178.2 seconds. Sonnet rejected the v30 fixed-object review schema with HTTP 400 after
  675 ms and generated no review tokens. The run was cancelled before a second architecture chain.
  Cleanup removed its tagged no-traffic revision. Staging traffic stayed on the existing revision.
- Critic v31 keeps the four named MECE layers and five named proofs. It moves repeated assessment
  fields into shared positional rows and maps them back to named fields before domain validation.
  The field legend in the prompt is generated from the same server field map, so row order has one
  owner. The raw and Anthropic-adapted schema are both 1,274 bytes. Boundary tests cover every row
  arity, position types, all 27 rubric codes, topology code 17 coupling, adapter `$defs` and `$ref`
  preservation, and passing-layer locks. An exact one-token Sonnet 5 medium probe accepted this
  schema and stopped at the requested one-token cap.
- Diagnostic `31236639491` ran one protected `graph-expansion` case on exact head `15cb03a`. Both
  requested turns completed their Opus architect, Opus challenger, Kimi topology, and synthesis
  calls. The first Kimi object failed before rendering at `components[20][4]` with an invalid lane
  enum. The second failed at `composition.steps[16][0]` because the step used the component index
  namespace while v11 expected a component-row index. The critic was never called. The run made
  nine application calls, zero judge calls, and recorded $1.331445 application cost. Cleanup removed
  the no-traffic candidate revision and staging traffic remained on the prior revision.
- V12 removes tier and lane from the repeated topology tuples. Applied graphs omit the network tier
  badge because the authored topology does not contain a separate network-accessibility fact. The
  server derives the bottom lane only from a validated operations group. Lane is no longer a mutable
  component field, so composition repair and component locking have separate owners. Links, groups,
  and composition steps now share component indexes. Steps accept only non-root indexes from 1
  through the final component and retain strict duplicate and range validation. The authored
  sequence remains intact because parent-first tree order cannot establish runtime chronology.
  Compact tuple output, provider schema size, resource budgets, and all semantic topology fields
  remain unchanged.
- Diagnostic `31238039667` ran the protected two-turn `graph-expansion` case on exact head
  `34d17f6`. Kimi returned complete topology objects of 9,491 and 8,476 characters. Both were
  rejected before rendering at aggregate path `composition.groups`, rule `topology`, because at
  least one component was absent from the separate group membership arrays. The graph critic and
  semantic judge were never called. The run made nine application calls and recorded $1.332952 in
  application cost. The workflow cleanup removed the candidate tag, and staging traffic remained
  100% on the stable revision.
- V13 removes that cross-record exact-partition trap. Group definitions are compact `[label,kind]`
  rows, and each root or component tuple carries one required `group_index`. Tuple arity gives every
  component one assignment; the server validates each reference at its component path. Unused group
  definitions have no graph effect and are dropped during enrichment. Exact duplicate definitions
  share one identity. Distinct labels that collide after bounded normalization still fail closed.
  The provider schema is 844 bytes, and the worst-case topology serialization fell from 46,228 to
  44,608 characters.
- Diagnostic `31241232161` ran the protected two-turn `graph-expansion` case on exact head
  `f5f83ad`. Turn one produced a 33-node, 53-edge candidate and the private browser rendered every
  record without overlap or clipping. The critic call completed, then review postprocessing raised
  `ValueError`; the candidate was withheld. Turn two selected an unrelated 10-node, 3-edge canonical
  graph. The old evaluator combined turn evidence, accepted counts without exact identities, and left
  semantic review non-blocking. Ten eager node-detail calls were made. Application cost was
  $1.100258. This run supplied the reproduction for typed graph lifecycle state, strict MECE review
  validation, monotonic layer locks, exact per-turn D3 identity, and removal of eager detail calls.
- Critic v34 binds every semantic rubric code and deterministic finding to one server-owned MECE
  layer and rejects any model scorecard that classifies it under another layer. Its production
  topology evidence uses a cited witness subgraph plus directed endpoint claims. The server rejects
  nonexistent routes, unproved cycles, duplicate evidence, and edges outside every claimed route.
  Semantic sufficiency remains with the independent critic. Published applied graphs use bounded
  patch handling for edits and rewrites, including whole-graph rewrite language. A distinct new system
  design creates a new artifact. Any failed patch preserves the last approved graph.
- Diagnostic `31246433859` ran only `graph-expansion` on exact head `bf8180d`. Kimi produced a
  42-node, 62-edge candidate. The private browser inherited the live 656x848 split pane and reduced
  node titles to about 6.3 pixels. Sonnet rejected connection and render defects. The Kimi max patch
  accepted the stream but reached the remaining 210.9-second request window before it emitted a
  final patch. The adapter made one provider attempt and preserved the candidate. Known application
  spend, excluding the cancelled patch with incomplete provider usage, was about $0.856549. This
  isolated two general faults: the repair request repeated locked detail, and private review inherited
  a user-controlled pane shape.
- Diagnostic `31249964798` ran only `graph-expansion` on exact head `d474b40`. Opus produced the
  architecture and Kimi produced a 34-node, 64-edge candidate. The fixed 1440x960 browser report
  measured zero node or edge clipping, zero overlap, and 14.68-pixel minimum node titles. Seven of
  eight overview labels were visible. The `HTTPS inference request` label was placed 14.34 pixels
  beyond the left frame because edge-label collision candidates had no bounds check. The deterministic
  gate correctly withheld the clipped graph before critic or repair calls. Four application calls cost
  $0.682831; no judge call ran. The renderer now bounds every measured label candidate and fallback on
  both axes before collision checks. A 34-node, 64-edge multi-track regression covers the live level
  distribution without retaining domain-specific topology.
- Diagnostic `31255291000` ran `graph-expansion` on exact head `41f4881`. Both Opus architect
  attempts failed before token acceptance with Anthropic `overloaded_error`. Graph construction and
  critic validation did not run. The written synthesis call cost $0.067999. A delayed retry was
  permitted only after Cloud Run logs identified the provider error.
- Diagnostic `31255655951` retried the same case and exact head. The first Opus architect attempt
  received `overloaded_error`; its second attempt completed. The challenger and Kimi builder also
  completed. Kimi produced a 46-node, 67-edge, 5-group prototype candidate. The private 1440x960
  render showed all 46 nodes and 67 edges, zero clipping or overlap, 13.44-pixel minimum text, and
  all eight required overview labels. Sonnet accepted the critic request, then the local stage
  deadline cancelled it after 102.223 seconds without terminal output or usage. The candidate was
  withheld as `semantic_review_timeout`; no repair or judge call ran. Fully priced calls cost
  $0.669823. Known critic input and cache-write usage raises the known minimum to $0.717704, plus
  unreported critic output or thinking.
- The timeout exposed one depth contract across two boundaries. Prototype validation ignored
  production topology proofs after a completed response, while the provider schema and prompt still
  required five exhaustive proof rows. Initial critic admission also reserved 240 seconds for a
  future patch and second critic before the first verdict existed. A prior completed prototype
  critic on a smaller 33-node, 53-edge graph took 134.735 seconds, so the 102.223-second allowance
  was already below observed demand.
- Critic v37 gives prototype reviews a four-layer scorecard with an empty topology-proof object.
  Production keeps all five proof rows and their directed witness contract. Critic admission now
  preserves synthesis, finalization, and orchestration while allowing the active verdict to borrow
  up to the existing 180-second ceiling. Patch admission decides the remaining repair budget after
  a failed verdict. This removes unused prototype work and gives the current gate priority over a
  speculative later stage.
- Diagnostic `31256929226` ran `graph-expansion` on exact head `e645bf2`. All five logical model
  calls completed without fallback. Kimi produced a 36-node, 58-edge, 5-group prototype candidate.
  The private render had zero clipping or overlap, 14.68-pixel minimum text, and all eight overview
  labels visible. Sonnet completed the depth-aware review in 64.356 seconds and rejected one
  connections-layer reconciliation defect. The review carried model-owned `repair_scope=global`,
  so routing withheld the candidate without calling the bounded Kimi patch. The run cost $0.771274;
  no judge call ran.
- Critic v38 derives repair scope from the server-owned MECE layer results. No failed layer maps to
  `none`; any components, connections, or composition failure maps to `local`; a render-only failure
  maps to `global`. Model scope remains a validated wire field for compatibility and cannot bypass
  the bounded repair lane. A changed patch still requires a second independent review before
  publication.
- Diagnostic `31257810429` ran `graph-expansion` on exact head `122b1fd`. All eight application
  calls completed without provider fallback. Kimi produced a 41-node, 73-edge, 7-group candidate.
  The private render passed with zero clipping or overlap. Sonnet's first review rejected fallback
  branch completion and four reversed actor edges. Kimi applied the declared local repair in 97.441
  seconds, adding the missing fallback terminal edge and removing the four cited edges. The second
  review then rejected a cache-hit gate-preservation defect. Exact graph comparison proved that the
  cache path, its nodes, and every incident edge were unchanged by the patch. The defect was visible
  in the first candidate: cache hits could serve before rejoining the input guardrail and policy
  paths, with no accepted-post-gate cache-fill edge. The first critic discovered defects serially.
  The one-revision limit then withheld the improved candidate. The run cost $1.065204; no semantic
  judge call ran.
- Critic v39 runs one clean completeness review of an initial editable rejection before spending the
  single Kimi repair. It supplies the first protocol-valid scorecard against the same candidate and
  render. The completion must retain every earlier blocker, selector, context anchor, deterministic
  finding, addition count, composition append count, and failed topology proof. Server validation
  rejects any narrowing before the patch worker runs. Initial approval, render-only rejection, and
  post-patch review keep one critic pass. The shared critic stage may borrow saved upstream time up
  to 195 seconds. A replay of the measured run offsets leaves 98 seconds for Kimi and 101 seconds
  for the final critic inside the existing terminal deadline and downstream reserves.
- Diagnostic `31259489721` ran `graph-expansion` on exact head `93bc29b`. Opus architect and
  challenger, Kimi construction, the private render, and both Sonnet protocol attempts completed.
  The 48-node, 71-edge, 5-group prototype graph passed deterministic and browser checks. The initial
  critic and its low-effort correction each returned provider-valid JSON that failed the Python
  scorecard contract. No completeness pass or Kimi repair ran. Six calls cost $0.816763. Retained
  evidence records `ValueError` without a path, so the exact model-owned value is unavailable.
- Critic v40 removes the known serial protocol traps before another paid run. Its generated pass-row
  example now uses a valid `0.9` score. The server derives layer status from blockers, places failed
  scores below the publish threshold, rejects low scores that omit a blocker, and derives repair scope.
  A bounded preflight reports independent layer-row and production-proof defects together to one
  medium-effort correction and completeness audit. The prompt states the existing component, connection,
  endpoint, and grouped-composition permission dependencies. Every terminal protocol rejection emits
  a safe validation stage, path, and rule in the captured workflow event without retaining model text.
- Diagnostic `31261404727` ran `graph-expansion` on exact head `bf3bde1`. Opus planning and
  challenge, Kimi generation, private rendering, and both Sonnet review passes completed without a
  provider retry or fallback. Kimi produced a 24-node, 57-edge, 5-group prototype candidate. The
  initial critic returned a protocol-valid local rejection. The clean completion pass then changed
  the connections blocker set, and the server rejected it at
  `completion/connections.blocking_findings/non_monotonic_completion`. No Kimi patch ran. Six calls
  cost $0.856352. The failure was an ownership defect: an independent completion had to reproduce
  the first pass's derived blocker strings exactly even when it expanded the same context.
- Critic v41 makes validated repair authority server-owned. The server takes an ordered union of
  both valid pre-patch reviews, retains prior selectors and failed proofs, takes the higher addition
  permissions, derives status and scope, and validates the merged contract before Kimi receives it.
  The completion pass can add findings without restating the lower bound. It cannot revoke prior
  repair authority.
- Diagnostic `31262285743` ran `graph-expansion` on exact head `3c2ceaa` while exact-head offline CI
  passed. Opus planning and challenge completed, then Kimi returned a provider-valid topology. The
  local parser rejected `root[1]` with `value_type` before rendering because the shared tuple schema
  permits strings in every position while categorical decoding accepted only integer codes. Four
  calls cost $0.602776; no critic, patch, or judge call ran.
- Applied topology decoding now accepts either the documented integer code or its canonical finite
  codebook name at every categorical position. It normalizes known decimal code strings, case, and
  surrounding whitespace, then rejects unknown names, booleans, and foreign codes. Indexes remain
  integer-only.
  This resolves the provider-schema mismatch without another Kimi call or a provider-specific
  positional schema.
- Diagnostic `31263053030` ran `graph-expansion` on exact head `84f628f` while exact-head offline CI
  passed. The normalized Kimi topology reached private rendering and both Sonnet pre-patch reviews.
  The server merged their local repair authority for a 42-responsibility candidate. The Kimi patch
  was cancelled after 142.051 seconds because the dynamic deadline retained the final critic and
  synthesis reserves. The complete turn took 719.136 seconds and withheld the unpublished candidate.
  Earlier protocol and topology fixes worked; this failure was isolated to repair latency.
- The primary architect remains Opus 5 at xhigh. The dependent challenger now uses Sonnet 5 at
  medium because it reviews a complete primary plan and does not own the design. The last Opus
  challenger consumed 140.737 seconds. The repair cap is 180 seconds. The backend, browser, and
  Cloud Run boundaries are 940, 970, and 1000 seconds so each outer layer retains 30 seconds for a
  typed terminal result and persistence. The complete admitted repair path still retains the final
  critic and synthesis reserves.
- Diagnostic `31264351143` ran `graph-expansion` on exact head `1ac7ac7` while exact-head CI
  passed. Moving the challenger to Sonnet reduced that stage from 140.737 to 32.058 seconds. Opus
  planning took 111.089 seconds and Kimi topology generation took 177.457 seconds. The application
  turn completed in 344.639 seconds, down from 719.136 seconds. Kimi returned provider-valid JSON,
  then local validation rejected the fifth component's parent reference at `components[4][0]`.
  No critic or patch ran.
- Parent-reference decoding now preserves valid zero-based topology and also accepts a complete,
  consistently one-based parent set by converting every parent reference together. Mixed conventions,
  forward references, cycles, non-integers, and out-of-range indexes still fail closed. The topology
  prompt includes concrete first-row and fifth-row bounds so the provider does not need the fallback.
- The WebSocket emits a provisional design frame after the architect finishes and before Kimi
  topology generation. It carries the interpreted plan and bounded assumptions. The exhaustive
  Sonnet graph critic owns the independent acceptance review; the pre-generation challenger is no
  longer on the graph publication path.
- Historical v42 transition: post-patch semantic review was authoritative. The removed layer-fingerprint lock could overwrite a
  newly discovered defect in an unchanged layer with an earlier pass result. Patch-time mutation
  locks still prevent Kimi from changing graph fields outside the approved repair contract.
- Critic v42 removes model-owned repair scope, layer status, and layer score from the wire protocol.
  The server derives pass or fail from blocker evidence, assigns the internal binary score, and maps
  failed layer ownership to repair scope. The provider grammar now accepts only the integer and array
  values used by the compact rows. This removes contradictory protocol states before the next paid run.
- Canonical run `31221851568` completed all Kimi provider calls. Two valid topology objects were
  discarded because one bounded title and one bounded responsibility exceeded presentation limits.
  Two other 33-node and 39-node candidates passed browser rendering, then their Sonnet reviews were
  cancelled at about 43.5 seconds by the former 45-second stage cap. One Opus challenger reached the
  former 120-second cap. The run provides no completed semantic verdict on those graph candidates.
- Offline CI `31085357395`: success on `4d7dcb3` before the repair-ID change.
- Diagnostic `31056353630`: initial graph and critic both executed; failure is isolated to focused repair validation.
- Diagnostic `31127543972`: edge IDs were accepted; the patch call hit exactly 3,200 output tokens and the server preserved the existing graph because no JSON object was emitted.
- Diagnostic `31127721414`: the first repair published a valid candidate; the second repair failed because the patch protocol omitted and inconsistently required presentation fields.
- The current stabilization tree passes 1,315 tracked backend tests at 91% total coverage. The
  frontend passes 218 tests with 91.15% statements, 78.94% branches, 93.23% functions, and 93.52%
  lines. Static analysis, dependency audits, ingestion artifacts, migrations, Terraform validation,
  the production frontend build, and the backend container build pass on the same working tree.
- Backend/frontend staging readiness, dashboard smoke, capture, cleanup, artifact upload, latency accounting, and cost accounting all passed.
- `main` contains PRs #37 through #40. Diagnostic `31335429802` later failed at
  `architecture_pass_evidence_provenance`. Any follow-up paid diagnostic requires fresh explicit
  authorization.
- Diagnostic `31369358742` ran only `graph-expansion` on exact merged head `77df25e7`. The Opus
  architect completed at high effort in 111.877 seconds, then the server rejected
  `evidence_basis[2].evidence_ref`. Cloud Run recorded the private rule `unknown_evidence_id`; the
  public artifact retained only `invalid_evidence_reference`. The model had been asked to reproduce
  a 69-character hashed source ID. No graph, private render, Kimi, Sonnet, repair, judge call, or
  second turn ran. The application made two logical calls across three provider attempts, took
  153.688 seconds for the turn, and cost $0.300365. The green workflow was report-only because the
  corpus remains pending human review.
- Canonical evidence records keep their stable hashed IDs. Architecture models now see deterministic
  request-scoped slots such as `source_1`, and the server accepts only those slots at architecture
  model boundaries before resolving them to canonical IDs for provenance validation and storage.
  The same translation hides internal IDs in the challenger candidate. Later graph and synthesis
  prompts omit the canonical coordinates while retaining evidence claims. Unknown slots,
  source-type mismatches, and model-supplied canonical IDs retain the existing fail-closed validator
  and generic public error.

## 2026-08-12 convergence and latency state

The recent diagnostic failure ledger above is the canonical status and chronology. The entries
below retain implementation detail for the latest convergence and latency corrections.

### Preview-first graph state machine

The serial Opus-first path is retired. Initial graph creation now follows this order:

1. Kimi K3 authors one topology candidate at low effort directly from the request, selected depth,
   and server-owned topology contract. The call has one provider attempt.
2. The server validates and normalizes the topology, then asks the browser to render that exact
   candidate privately.
3. A candidate that passes the deterministic browser gate is emitted as a reversible preview.
4. Opus 5 medium audits the exact candidate against the request and evidence. Its plan supplies
   review commitments and has no mutation authority.
5. Sonnet 5 medium returns the exhaustive semantic scorecard. Publication still requires its latest
   full-graph pass. Local failures use the existing exact-record Kimi repair contract and
   dependency-aware layer locks.
6. The transport emits authoritative `graph_data` only after turn persistence. Rejection, timeout,
   cancellation, steering, or persistence failure restores the request-start approved graph.

Initial topology and private rendering use a separate 170-second preview deadline. Topology has a
140-second provider cap, private rendering retains its 15-second cap, and 15 seconds remain for
preview finalization. Post-preview review and repair retain the terminal workflow deadline. The
frontend stores preview and durable graphs separately, never writes preview view state, and promotes
only an authoritative `graph_data` event.

Kimi does not support medium. Supported values are low, high, and max. Initial topology uses low
because the independent Opus and Sonnet reviews protect publication quality and high effort has
exhausted the preview deadline without emitting topology. Kimi repairs remain high. Opus and Sonnet
remain medium. The next protected diagnostic must measure latency and first-pass acceptance; offline
tests cannot establish provider response time.

- Diagnostic `31610799035` on exact head `fd61175` ran one `graph-expansion` case with the
  preview-first state machine. Kimi high received one attempt with no fallback and ran for 138.118
  seconds. Reasoning began after 6.801 seconds, but the provider emitted no topology text before the
  available design window expired. No graph, private render, architecture review, semantic review,
  or second turn ran. The fallback synthesis took 27.344 seconds. Turn latency was 168.609 seconds
  and case latency was 170.290 seconds. The run used two application calls and no fallback. Known
  Opus cost was $0.063504; total cost was unavailable because Kimi returned incomplete usage.

- Diagnostic `31598216294` on exact head `ccd5c77` ran one `graph-expansion` case. Opus medium
  completed in 89.249 seconds. The following Kimi low call ran for 88.507 seconds, began reasoning
  after 8.427 seconds, emitted no topology text, and was cancelled at the 180-second browser limit.
  No graph, private render, critic call, second turn, or fallback occurred. Known Opus cost was
  $0.152365; Kimi cost was unavailable because the cancelled provider response contained no usage.
  This run proved that two serial model calls before preview cannot reliably meet the visible-graph
  contract.

- Diagnostic `31588931923` on exact head `ca8e3b2` ran one `graph-expansion` case. Architecture
  validation rejected `evidence_basis[8].evidence_ref` under the private
  `invalid_engineering_area` rule after two calls. The turn took 107.735 seconds, the case took
  109.568 seconds, and application cost was $0.236575. Kimi, private rendering, critic review, turn
  2, and fallback did not run. The workflow wrapper concluded green only because pending-corpus
  diagnostics are report-only. Engineering-recommendation references are internal checklist
  classifications, so they do not belong in external `evidence_basis` validation. This diagnosis and
  its intended contract correction have no live success evidence.
- Diagnostic `31549644038` on commit `b64f66f` restored medium architect effort and produced a valid
  plan in 78.784 seconds. Kimi returned after 81.252 seconds, but deterministic topology validation
  rejected `connections.links[6]` with rule `topology` before private rendering. No preview or Sonnet
  review ran. The browser stopped turn one at 180.083 seconds with no fallback; turn two did not run.
  Three application calls ran. The two completed priced operations cost at least $0.232051; the
  cancelled synthesis call left final cost incomplete. Retained telemetry cannot distinguish an
  out-of-range endpoint from a self-link because authored model output is not stored.
- Diagnostic `31549117335` on commit `1a279b6` stopped before graph generation because the
  low-effort prototype architect exceeded a hard plan-list limit. The fail-closed boundary returned
  `architecture_pass_list_limit`; Kimi and Sonnet were never called. Turn one ended in 88.836
  seconds after two Opus calls, with no fallback, at $0.201845. Prototype architecture effort is
  restored to medium because diagnostic `31547774792` proved that setting produced a valid plan.
- Diagnostic `31547774792` on commit `67887c3` enforced the new deadline and stopped turn one at
  180.122 seconds. The deterministic private render had passed at 127.374 seconds, but no visible
  preview was emitted. The initial Sonnet review then produced an over-broad composition repair
  contract. Local admission rejected it at `layers.composition.group_ids: unbounded_collection`,
  and the deadline cancelled its correction call. Four application calls ran, fallback stayed off,
  and turn two did not run.
- The prior diagnostic on commit `9a3dcd2` spent 370.581 seconds on turn one and withheld the
  graph. The active application calls were Opus architecture, Sonnet challenger, Kimi topology,
  Sonnet review, Kimi patch, Sonnet post-patch review, and Opus explanation.
- The challenger is no longer on the graph publication path. The Opus architecture pass uses
  medium effort with a 12,000-token completion ceiling.
- Prototype review treats `logical_flow`, `authored_composition`, and `branch_completion` as advice
  when the graph is connected and renderable. The same findings remain blocking at production
  depth. Disconnected paths, missing primary outcomes, and requested missing paths remain blocking
  at every depth. Stored prototype-advisory findings cannot re-enter a later prototype review as
  stale repair obligations.
- The topology wire object declares one required `index_base`, either 0 or 1. That declaration owns
  every parent index, link endpoint, group membership index, and composition step index. The server
  converts every reference to canonical zero-based indexes before topology validation. It no longer
  infers parent and link conventions independently. References invalid under the declaration,
  self-links, duplicate links, and links duplicating tree edges fail closed. This removes the
  ambiguous representation class that remained after diagnostic `31549644038`.
- Composition batches select primary runtime-sequence membership only. The topology prompt requests
  one batch. The server accepts nested batches for compatibility, but their order and boundaries
  have no semantic authority. It derives each selected node's stage as its shortest directed distance
  from the root across selected tree edges and explicit runtime links. Invalid indexes, duplicates,
  a missing root, and unreachable selected nodes still fail closed. This removes the conflicting
  model-authored order that caused diagnostic `31612168038`.
- Passing review layers retain their prior verdict. Component changes reopen components,
  connections, and composition. Edge changes reopen connections and composition. Composition-only
  changes reopen composition. A prototype-to-production transition reopens connections and
  composition so production topology proofs cannot be inherited from a prototype review.
- One record-scoped patch may edit several exact disconnected regions. Every edited record remains
  named in the repair contract. Moving a node requires authority for both its source and destination
  groups. Invalid patches preserve the candidate and receive at most one error-informed contract
  correction. The workflow permits at most two successful semantic repair rounds.
- A graph that passes deterministic graph and browser-render checks is emitted as a reversible
  preview while semantic review continues. The transport emits authoritative `graph_data` only after
  review and persistence, and restores the prior graph if the turn does not commit. The
  `graph-expansion` live case records `graph_output_latency_ms` for each turn, actively
  stops either turn with no visible graph by 180,000 ms, and reports `required_graph_slow`. A safe
  `render/complete` progress event now separates accepted private rendering from preview transport
  without exposing authored graph content.
- Scoped expansion first resolves exact authored IDs and labels. Its stemmed token fallback now
  prefers one exact token set before considering broader subset matches. A request for Monitoring
  cannot become ambiguous only because Monitoring Alerts also exists. Duplicate exact matches and
  multiple broad matches still fail closed.
- Prototype architect calls omit production-only system rules and do not repeat an identical request
  as design context. Kimi authors the reversible initial candidate before Opus and receives no
  model-authored architecture plan. Opus then audits the exact candidate. The current efforts are
  Kimi K3 low for initial topology, Kimi K3 high for patching, Opus 5 medium for architecture review,
  and Sonnet 5 medium for semantic review. This order is offline-tested; no live latency improvement
  is claimed.
- LLM telemetry records safe character counts and per-attempt time to first reasoning and text
  deltas. The protected eval endpoint exposes those counts without prompts or authored output so a
  future diagnostic can separate prompt ingestion, reasoning, and constrained decoding time.

## Known pre-run risks

- The 180-second visible-graph target remains live-unverified for Kimi low in the preview-first path.
  The separate preview deadline removes the serial Opus call, limits Kimi to one provider attempt,
  and reserves browser render time. The next protected case must prove that low effort completes the
  topology and that the downstream quality gates accept or safely repair it.
- Production topology proofs still allow reviewer-owned `not_applicable`. The server has no trusted
  semantic scope that states which of the five flow classes apply to a request. Deriving that scope
  from node labels, types, or the reviewer output would make model-authored text an authority. A
  later protocol may add a server-owned topology scope established before review. This release keeps
  the existing rule and records the gap.
- Turn-two patch latency remains live-unverified on the new head. Offline tests prove call ceilings,
  mutation authority, candidate preservation, and corrected contract behavior with mocked providers.
  They cannot prove Kimi response time or first-pass acceptance.

## Evaluation workflow lessons

1. Provider-supported JSON Schema is smaller than general JSON Schema. Unsupported cardinality keywords cannot be treated as enforcement.
2. A schema can be valid but too expensive for the provider grammar compiler. Repeated optional properties and divergent enums multiply grammar complexity.
3. Structured output guarantees shape better than semantics. Empty strings, enum casing drift, and normal `end_turn` responses still require a provider-to-domain normalization boundary.
4. Fixed identifiers are useful, but numeric slot order must not be confused with dependency order.
5. Deterministic normalization should repair representation, not certify semantics. The independent critic and publication validator remain mandatory.
6. Patch selectors and authored values need different representations. A short repair-only ID preserves identity without asking a model to copy mutable prose or assuming endpoint pairs are unique.
7. Preserve safe telemetry at every boundary: finish reason, response size, validation path/rule, normalization action, operation stage, and match count. Do not log prompts or authored content.
8. A public `graph_emitted=false` code is insufficient for operations. It hid grammar compilation, truncation, topology, mutation-role, critic, and patch failures behind one predicate.
9. Diagnostic cases are appropriate for iterative debugging, but they cannot publish an
   `approved-tree-*` tag. PR-tree approval still requires one canonical complete eight-case run;
   corpus approval separately requires the complete 20-case capture and review.
10. Exact-tree identity is required for safe approval reuse across squash merges; commit SHA equality alone is insufficient.
11. Keep the model wire schema separate from the domain contract when provider grammar limits would
    force duplicated definitions. Convert once at the provider boundary and validate the canonical
    domain form before any mutation decision.
12. Evaluation evidence must remain attached to one turn and one graph version. Counts are capacity
    checks, but they cannot prove that the expected graph reached the DOM.
13. Treat a strong candidate as durable unpublished state. A local review or patch failure preserves
    that candidate for bounded correction. It does not authorize topology regeneration or canonical
    fallback.

## Remaining execution order

1. The full offline gate has passed on the current tracked tree.
2. Obtain fresh authorization before another protected `graph-expansion` diagnostic on the exact
   PR head containing the new index-base and expansion-target corrections. Require both turns to
   publish within 180 seconds without fallback
   while preserving the first graph during expansion. Use the safe phase telemetry to identify any
   remaining boundary.
3. After that diagnostic passes and separate fresh explicit authorization, run one uninterrupted
   canonical eight-case PR evaluation on the same tree.
4. Run a full protected 20-case capture, complete human review and judge recalibration, and publish
   the approved manifest required for corpus `2026-08-12.v1` to block or promote.
5. Verify the exact-tree approval tag and required PR checks, then merge with the final-head guard.
6. Monitor the `main` production workflow through immutable backend deployment, smoke/promotion, and Vercel deployment.
7. Verify Cloud Run revision, digest, traffic, and the public backend and frontend URLs.

## Repository and contributor notes

- The README has been updated during this stabilization branch.
- GitHub collaborator inspection did not show Claude as an active repository collaborator. The screenshot entry is contributor/history attribution, which is not removed by collaborator permissions.
- `Agent-eval-research-security` and `Agent-live-eval-parallel` were branch/worktree names used during evaluation work, not live production services.

## Completion definition

This effort is complete only when all of the following are true on authoritative current evidence:

- Exact final PR head has required offline CI success.
- A canonical eight-case PR evaluation resolves every previously failing PR-gate case without
  infrastructure failure.
- A full protected 20-case capture receives human review, judge recalibration, and an approved
  manifest for corpus `2026-08-12.v1`.
- The exact Git tree has a valid protected-evaluation approval.
- PR #37, PR #38, and PR #39 remain present in `main` history.
- The Kimi role-routing change is present in `main` and its first-pass acceptance evidence is recorded.
- `main` deployment completes for the tested tree/digest.
- Cloud Run serves the promoted revision and passes public health/smoke checks.
- Vercel serves the current frontend deployment at the production alias.
