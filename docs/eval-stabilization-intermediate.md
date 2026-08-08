# Live Evaluation Stabilization: Intermediate Record

Last updated: 2026-08-08

This document records the stabilization work through PR #41 (`codex/restore-live-eval-gate`) and the remaining production exit criteria. PRs #37 through #40 merged on 2026-08-07. PR #41 now contains the exact-tree live gate, compact Kimi topology boundary, MECE review contract, bounded repair workflow, fixed publication frame, and bounded label placement. It still needs one protected graph diagnostic, the canonical evaluation, merge, and deployment verification.

## Objective and operating rules

- Make the protected eight-case live evaluation pass on the exact PR tree.
- Avoid repeating paid successful cases while debugging. Use `Scheduled evaluation` with `suite=diagnostic` and one unresolved case at a time.
- Run one final uninterrupted canonical eight-case evaluation only after targeted failures pass.
- Require free offline CI before any paid diagnostic.
- Cancel automatically triggered live workflows while a newly pushed head is not CI-verified.
- Publish/consume approval by Git tree identity so squash commits and synthetic PR merge refs cannot invalidate equivalent content.
- Preserve PR #37's two reviewed commits and merge the focused contract correction.
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

This subsection records the fixed-slot contract used by the earlier stabilization branch. The current
runtime supersedes it with variable arrays, model-authored groups and sequence, strict reference and
cycle validation, and resource-safety ceilings that are absent from model prompts. It never truncates
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

The product target is a one-shot, publishable architecture diagram. Opus 5 xhigh writes the primary
architecture brief, then performs a clean second-pass review before graph construction. Kimi K3 low
owns initial graph topology. Kimi K3 high applies one typed local repair to a rejected unpublished
candidate and handles user refinements to a previously published graph. Sonnet 5 medium reviews architecture
semantics and the private browser screenshot before publication. The protected semantic judge also
defaults to Sonnet 5 high.

The workflow now permits one repair after the first candidate. A second failed QA result suppresses
the graph. Normal operation should publish the first candidate; repair rate and first-pass acceptance
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

## Current checkpoint

PR #37 preserved `87c9012` and `cbbc892` as its two reviewed commits. The post-merge contract correction is isolated in one follow-up commit.

Current implementation state:

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
- A passing layer is retained across one bounded repair when its full dependency fingerprint is
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
- The current stabilization tree passes 1,034 tracked backend tests at 90% total coverage. The
  frontend passes 214 tests with 91.32% statements, 79.02% branches, 93.33% functions, and 93.64%
  lines. Static analysis, dependency audits, ingestion artifacts, migrations, Terraform validation,
  the production frontend build, and the backend container build pass on the same working tree.

Most recent authoritative evidence:

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
- The WebSocket now emits a deterministic design frame after the architect and challenger finish,
  before Kimi topology generation. It carries the interpreted plan, bounded assumptions, and the
  challenger risks. The final stored answer contains the same frame, so a slow graph call no longer
  leaves the user without useful architecture text.
- Post-patch semantic review is authoritative. The removed layer-fingerprint lock could overwrite a
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
- The current stabilization tree passes 1,034 tracked backend tests at 90% total coverage. The
  frontend passes 216 tests with 91.32% statements, 78.96% branches, 93.23% functions, and 93.65%
  lines. Static analysis, dependency audits, ingestion artifacts, migrations, Terraform validation,
  the production frontend build, and the backend container build pass on the same working tree.
- Backend/frontend staging readiness, dashboard smoke, capture, cleanup, artifact upload, latency accounting, and cost accounting all passed.
- `main` contains PRs #37 through #40. PR #41 now needs one v42 exact-tree diagnostic before the
  canonical run.

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
11. Keep the model wire schema separate from the domain contract when provider grammar limits would
    force duplicated definitions. Convert once at the provider boundary and validate the canonical
    domain form before any mutation decision.
12. Evaluation evidence must remain attached to one turn and one graph version. Counts are capacity
    checks, but they cannot prove that the expected graph reached the DOM.
13. Treat a strong candidate as durable unpublished state. A local review or patch failure preserves
    that candidate for bounded correction. It does not authorize topology regeneration or canonical
    fallback.

## Remaining execution order

1. Pass the full offline gate on the exact tracked tree.
2. Run one protected graph diagnostic and require a publishable first candidate or one valid bounded repair.
3. Run one uninterrupted canonical eight-case protected evaluation on that tree.
4. Verify the exact-tree approval tag and required PR checks, then merge with the final-head guard.
5. Monitor the `main` production workflow through immutable backend deployment, smoke/promotion, and Vercel deployment.
6. Verify Cloud Run revision, digest, traffic, and the public backend and frontend URLs.

## Repository and contributor notes

- The README has been updated during this stabilization branch.
- GitHub collaborator inspection did not show Claude as an active repository collaborator. The screenshot entry is contributor/history attribution, which is not removed by collaborator permissions.
- `Agent-eval-research-security` and `Agent-live-eval-parallel` were branch/worktree names used during evaluation work, not live production services.

## Completion definition

This effort is complete only when all of the following are true on authoritative current evidence:

- Exact final PR head has required offline CI success.
- The final canonical run resolves every previously failing case.
- One final canonical eight-case protected evaluation passes without manual review or infrastructure failure.
- The exact Git tree has a valid protected-evaluation approval.
- PR #37, PR #38, and PR #39 remain present in `main` history.
- The Kimi role-routing change is present in `main` and its first-pass acceptance evidence is recorded.
- `main` deployment completes for the tested tree/digest.
- Cloud Run serves the promoted revision and passes public health/smoke checks.
- Vercel serves the current frontend deployment at the production alias.
