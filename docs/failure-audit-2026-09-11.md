# Historical evaluation failure audit

Audited on 2026-09-11 using GitHub logs, retained result artifacts, source history,
and local reproductions. Historical collection required no paid models or deployments.
Fresh staging experiments are recorded separately below.

## September 12 AI pipeline reassessment

The last full capture, run `34663963035` at `de7bd658`, completed with 18/20 browser
cases passing, 15 semantic passes, three manual reviews, and two failures. It took
29 minutes 18 seconds. Known application and judge cost totals $3.790517; three
cancelled application attempts have unknown usage. No new provider calls were used
for the following diagnosis and offline changes.

- Graph expansion approved a baseline-store responsibility but authorized exactly
  one outbound edge. The reviewer correctly required returned data. The correction
  reversed the edge, then deterministic admission rejected its direction. The user
  asked for one responsibility, not one edge. Scoped attachments now allow one or
  two directions between the same anchor and new component; explicit counts and
  directions remain exact. A retained fixture tests both directions and rejects
  unrelated changes.
- The marketing candidate took 611.992 seconds and contained 20 nodes and 74 edges.
  A connection attempt timed out at 240 seconds. The next candidate had missing
  same-key reconciliation and failed/stale reuse outcomes, alongside a reviewer
  demand for separate edges for stream properties. Shared production criteria now
  consolidate 22 checks into 13 when every capability applies. Internal operations
  can remain with their executable owner. The missing retry and reuse outcomes
  remain blocking requirements. Model-written proof tables are removed.
- Text synthesis supplied the same design-heavy system prompt to memory, summary,
  and explanation requests. The shared system is reduced from 10,603 to 2,330
  characters. Depth controls detail within the task; graph-specific instructions
  apply only to graph answers. Prior assistant proposals are not user requirements.
- The judge received longer book passages than synthesis, and discarded directed
  flow and synchronization fields from its graph input. Release v6 consumes exact
  synthesis context when captured and retains public graph semantics. Older evidence
  is labeled as an incomplete record of synthesis input. A critical failure blocks
  immediately, including when another dimension is borderline.
- Calibration required all browser cases to pass before it could judge them.
  Complete captured product failures can now be negative calibration examples.
  Application release gates still fail on those outcomes; human grades and pinned
  evidence identity remain required.

These changes have offline regression coverage. The historical 18/20 result does
not validate the changed prompts, establish a new pass rate, or measure their live
latency. Component and connection authoring remain separate, with bounded correction
and preserved prior graphs on failure. The current architecture document records
that remaining repair boundary. Further model testing should target changed cases
after offline checks, then use one full capture for a release decision.

## Findings and scope

GitHub records identify **55 failed single-case `graph-expansion` diagnostic
executions**, plus seven cancelled single-case captures and one capture whose
browser and semantic outcomes both passed. The failed executions span August 8 to
August 19. Twenty-seven of the 55 workflows concluded `success` while their logged
`BROWSER_OUTCOME` and `SEMANTIC_OUTCOME` were both `failure`.

The [previous stabilization ledger](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger)
documents 32 of these 55 failures. It omits 23 older or intermediate executions.
Its root-cause descriptions are secondary evidence in this audit. A description in
that ledger does not replace an expired capture.

Seventeen failures retain browser captures, live results, and provider telemetry.
All 17 contain nonzero provider token usage and failed deterministic product
checks. The other 38 retain execution logs but their result artifacts have expired.
For those 38, the failed commands are verified; exact paid usage and the division
between product, infrastructure, and evaluation defects are unknown.

The retained captures have four recurring evaluator symptoms:

- 12 report `required_graph_missing`.
- Two report `graph_expansion_added_node_count_mismatch`.
- Two report `required_graph_version_reused`.
- One reports `graph_expansion_prior_assumption_missing`.

These symptoms describe the final product check. They do not identify every root
cause. For example, run `31705887318` records a failed `graph_critic` provider attempt
with zero output usage, while run `31900871827` records a failed graph-patch attempt.
Both fail a required-graph check. The older ledger attributes those
attempts to provider overload and a correction timeout, respectively; those more
specific explanations require evidence beyond the retained telemetry.

Across the 17 retained failures, median case latency is **250.153 seconds**. Sixteen
have complete estimated application costs: their sum is **$6.680770** and median is
**$0.304456**. Run `31900871827` has a null application-cost total because usage is
incomplete. These are historical estimates, not billing statements. They cannot
establish total spend across the 55 failures.

## Independent diagnosis and correction

The retained evidence supports a focused refactor of scoped edits and shared
review criteria. It does not establish a need to replace the provider stack,
renderer, storage, or orchestration framework.

### Generation and review had different obligations

Run `32291218614` rejected component coverage and objective fidelity. Run
`32295031180` first rejected capability classification, then introduced
`independent_risk_coverage`. The staged path had no independently reviewed risk
artifact. A gate could demand evidence that its pipeline never produced.

At the audited source head `e7227b4`, staged gates received rule names without the
canonical requirement text. Generation received detailed rubric requirements only
after rejection. The correction shares `staged_review_requirements` between both
stages and their reviewers. The first candidate and every correction receive the
same applicable criteria, including capability-dependent production proofs.
The stage still excludes rules whose upstream evidence does not exist.

### Scoped edits required models to copy locked records

Run `32300653373` first rejected its expansion at `component_write_set`. Source
inspection shows that generation received only component and edge capacities,
while later validators enforced specific record and field permissions. The model
had to regenerate the entire graph and infer its permitted changes.

Scoped generation now emits additions and field updates in server-selected slots.
The server copies retained records and applies authorized removals. Both stages
receive the actual edit permissions. Create generation keeps its existing wire
format. Existing final admission checks remain authoritative.

A committed fixture retains the exact five-node turn-one graph from this run.
The regression uses actual scope compilation, delta assembly, ID assignment,
projection, and final admission. It expands Monitoring Service to six nodes and
seven edges and passes the existing graph-expansion evaluator. Original nodes,
edges, title, assumptions, sequence, and prior group metadata remain exact.
Provider output, rendering, and semantic review are stubbed in this regression;
it proves the deterministic path and does not certify live model quality.

### Maturity and edit scope contradicted each other

Run `32298885657` published both turns but replaced prior assumptions during a
prototype-to-production transition. Run `32300653373` preserved assumptions, then
failed a production review of a locally scoped prototype edit. Keeping every
prototype record fixed cannot guarantee a graph-wide production upgrade.

The existing corpus correction selects `auto` for additive expansion. The product
now also rejects a scoped maturity change before model calls and asks the caller
to retain the stored maturity or explicitly rebuild the graph. Selecting a depth
or saying `replace Cache` cannot authorize whole-graph replacement.

### Deterministic bookkeeping created further failures

Local reproductions exposed deletion failures that paid-run symptoms did not
isolate. Removing an earlier component shifted model indexes, left incident edges
pointing at removed IDs, and made unchanged edge records appear updated by position.
Grouped prototype deletion also lacked membership-cleanup authority.

The correction retains server IDs and the root by identity, removes only authorized
incident edges, maps retained edges by identity, and permits cleanup in affected
groups. Tests reject unrelated node, group, and directed-edge mutations. Root
removal requires a separately authorized replacement and remains rejected.

Capability flags were also copied unconditionally from the base, so an addition
could introduce retrieval while its classification remained locked to false.
Capabilities are now proposed for the assembled candidate and reviewed before
connection proofs are chosen. Component fingerprints include the reviewed context,
so a flag-only correction can proceed and identical candidates still stop.

### A renderable graph could still fail semantically

Run `32009504451` omitted response routes, including a model-artifact return, while
all private renders passed. In `32054742321`, correction retained eight completed
connections and added an observational Monitoring Service to API Gateway control
edge. The final gate rejected that new edge for `edge_semantics` and
`safe_action_boundary`. The first gate's reasons were not retained, so the audit
cannot establish that the reviewer requested the harmful addition.

These cases support preserving accepted records and giving both models the same
criteria. Semantic gates and bounded corrections remain. The correction-only
control-edge restriction was removed: it accepted the identical graph on the
first attempt and rejected it after a generation failure. Both attempts now use
the same structural validator. Semantic review checks control behavior against
accepted responsibilities and capabilities.

Projection labels now describe node and flow types without inventing authentication,
durability, versioning, policy enforcement, or audit guarantees. Scoped edits retain
authored presentation fields. Review receives the prior objective and exact edit
context. Current-policy baseline reuse requires matching server-owned graph and
reviewer fingerprints; changed global obligations trigger full review. Every edit
still receives semantic review, including its effects outside the editable records.
Malformed reviewer findings fail explicitly instead of disappearing into approval.

### Evaluation could hide failure or report success without evidence

Twenty-seven historical diagnostic wrappers returned success despite failed
evaluation commands. Separately, the current required PR check returned success
when a pending corpus caused all protected work to be skipped. That required
status now fails with bootstrap instructions.
Scheduled runs now fail for any browser or semantic non-success, including pending
full-corpus proposals. They retain a deployment manifest and artifacts for 90 days.
Protected internal evaluations capture each gate result with its candidate
and review inputs, so a later rejection no longer erases the first gate's reasons.

Local reproductions found two further harness defects: an empty nightly capture
passed with zero evaluated cases, and missing application telemetry erased
deterministic failures and graph diagnostics. Nightly captures now require four
unique known cases. Missing telemetry remains an infrastructure failure, while
existing product failures keep their diagnostics and take precedence. Judge setup
is deferred until a case needs semantic evaluation.

## Fresh staging findings

The first protected diagnostic of the stabilization candidate,
[run 34649724600](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34649724600),
tested commit `d329888ec1903b3cfdbc8d50a98fe6e8566e480e`. Creation passed both
semantic gates and published eight nodes with fourteen edges. Expansion failed
at the component gate and retained the original graph. The workflow correctly
reported failure. Eight application calls cost an estimated $0.316342; no judge
call was needed after the deterministic failure.

The retained provider trace contains a valid rejection with a 538-character
reason. The local parser rejected that reason against a 280-character limit and
classified the gate as unavailable. The Anthropic schema adapter removes
`maxLength`, so the provider did not enforce this limit. The critique remains a
blocker after correction: the proposed Serving Log Explorer required the log
store, while its one permitted connection had to originate at Metrics Monitor.
The committed `staged_gate_34649724600.json` fixture preserves the exact response.

Reviewer reasons now use one 2,000-character bound through parsing, workflow,
and correction generation. Longer reasons remain blocking findings with an
explicit truncation diagnostic. Malformed fields, unknown rules, and invalid
witnesses still fail closed. Terminal results now reach protected capture with
their review identity, diagnostic, and available finish reason.

Component generation also lacked the exact connection addition plan. The model
received component slots but could not see the server-selected anchor and
direction. Both generation stages now receive that plan, including the exact
addition count and mapped component/addition indexes. The captured expansion
fixture verifies that Metrics Monitor maps to index 5 and must connect to new
component slot 0 on both the initial and corrected attempts.

After the failed expansion, explanation generation invented a different proposed
component and connection. Failed graph operations now emit their publication
status and existing revision guidance without another model call. Failure notices
no longer promise a written design that will not be generated.

The browser trace also exposed an independent routing defect. Adjacent vertical
edges travelled to a side gutter and retraced the same horizontal segment before
reaching the next node. The renderer now uses the free gap between adjacent rows.
Long, reverse, parallel, and wrapped routes keep their existing handling.

The follow-up candidate passes 1,808 backend tests at 91% coverage, 238 frontend
tests, frontend lint/build/audit, Python lint/security/dependency audits, and 131
CI policy tests. These checks include the exact captured reviewer response and
connection-plan regressions.

[Run 34651679217](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34651679217)
tested commit `aef874c8ebcbaea539a9f34f6106a37996a0776c`. The graph journey succeeded:
creation passed after one component correction, expansion preserved all five prior
nodes and added one responsibility, and both edit reviewers approved the first
attempt. The final six-node, ten-edge graph rendered and persisted. The first graph
appeared after 76.106 seconds on turn one and 23.626 seconds on turn two. Twelve
application calls cost an estimated $0.374289.

The workflow failed on `missing_worker:graph`. Staged generation emitted graph
progress and publication events but omitted the `worker_status` event that the
browser uses to identify executed workers. The pipeline now reports its graph
worker at entry. The evaluator's worker requirement remains unchanged.

Rollout inspection exposed two further consistency defects. A concept diagram
generated through the legacy path under staged mode could retain a prior staged
approval contract and fail persistence. Failed legacy edits also assigned a new
version to the restored graph while retaining its old contract. Legacy generation
now clears stale contracts, no-op output retains the prior version, and restoration
preserves a versioned approved graph. Top-level routing tests cover both pipelines
and transitions between applied and concept diagrams.

Scheduled diagnostics also left `GRAPH_PIPELINE_MODE` in the staging service's
configuration. Later protected PR evaluations inherited it. Deployments now resolve
and explicitly set the versioned backend default; manual scheduled evaluations can
select either mode. Deployment manifests record the effective value. The candidate
now defaults to staged applied graphs, with explicit legacy rollback. Full-corpus
validation and human review remain release requirements.

Calibration setup had a circular prerequisite: its CLI required aggregate corpus
approval, while aggregate approval required a passing calibration result. The CLI
now permits calculation after all case reviews and evidence pins are complete.
It still requires a full semantic replay and the existing agreement thresholds;
each human review must refer to the pinned capture run. Evidence promotion now
accepts reviewed candidate-branch captures after strict source, browser, dashboard,
and human-review validation. A semantic failure does not invalidate otherwise
complete browser evidence used for calibration. This does not approve an image.

The next independent pass reproduced three additional defects offline. A named
addition such as `Add Cache to Payment service` authorized the ID `cache`, but
the assembled candidate received `n3` and failed final admission. Named additions
now receive their exact server-authorized ID; generic expansion keeps generated
IDs. Prototype and production regressions cover both paths.

A failed pre-start WebSocket connection could schedule a retry, then restart the
cancelled request after the user stopped or submitted a newer request. Cancellation
now clears the retry timer and settles its promise. The callback also verifies
socket and request ownership before reconnecting. Both cancellation regressions
failed before the fix and pass afterward.

The SSE transport released its stream lease before persistence. A second replica
could read the older graph and later overwrite the first turn's committed graph
when preserving its own request-start snapshot. The lease now covers setup,
persistence, and terminal publication. Storage-backed tests deny a competing lease
at the commit boundary and verify cleanup on completion and failure.

Browser review HTML also truncated answers and retrieval evidence and omitted
earlier turn graphs. It now includes complete per-turn evidence and a digest/link
for the exact raw capture. Untrusted text remains escaped. This produces reviewable
evidence; it does not supply human grades.

The full run exposed a capacity regression before semantic evaluation. Staging
allowed four concurrent HTTP requests on one instance, while the browser runner
allowed four simultaneous cases. Four open WebSockets consumed every request
slot. Cloud Run logged fourteen capacity-related HTTP 429 responses, including
two WebSocket handshakes. These were platform capacity failures, not application
rate-limit responses. The new shared staging budget reserves sixteen request slots
and rejects configurations below twice the browser concurrency. Terraform and both
evaluation deployments read that budget; deployments verify and record the
configured value. The one-instance staging limit remains.

The first RAG runtime candidate also depicted an unrequested explainer application.
Its `Runtime Flow Modeler` owned downstream diagram construction. The initial
review rejected duplicated orchestration responsibilities; the corrected candidate
retained the modeler and the second review rejected diagram-authoring mechanics.
Shared objective and coverage criteria now distinguish the depicted subject's
runtime from instructions to explain, ground, or draw the response. Explicitly
requested explainer and diagram-authoring products remain valid domains. Changed
criteria invalidate prior component review identities. Live semantic effectiveness
must be checked on the next candidate.

The production marketing and document-processing cases each made two connection
generation calls that ended at approximately 129.94 seconds. Neither reached a
connection review. The staged caller supplied the same 130-second timeout on every
attempt, even when earlier stages finished below their budgets. The correction
uses the existing absolute-deadline admission layer for connections. It can borrow
unused time up to the existing 240-second builder limit while reserving the current
review, every remaining connection attempt and review, rendering, synthesis, and
finalization. Initial component generation retains its preview deadline.

The closed-loop evaluation case exposed an incomplete first review. Its first
review rejected `learning_or_release`; its second rejected `external_effects` on
unchanged component records. The candidate only owned dataset updates and described
a passive downstream registry. Shared capability criteria now require each true
flag to have a named owner for the relevant mutation or model change. This reduces
an ambiguous boundary; another live run must establish its semantic effect.

### Why earlier fixes did not prevent recurrence

Commit `1b1fe204` on July 19 raised staging concurrency from one to four so one
WebSocket left room for API requests. Commit `30c54b6` on August 2 raised browser
concurrency from two to four without increasing staging capacity. Tests asserted
the separate constants instead of the required relationship. The shared budget
and capacity invariant address that missing relationship.

Commit `8ac4a7f`, incorporated into `77df25e`, excluded diagram-authoring mechanics
in the legacy rubric and worker prompts. The later staged pipeline in `8f061d0`
bypassed those workers and supplied rule names without their requirement text.
Commit `d329888` restored shared requirement text and tests its projection into
both generation and review. The fresh semantic failure occurred with that text
present. It requires the explicit subject boundary and another real evaluation;
it does not show that the restored rule was deleted again.

Deadline admission was introduced in `cbbc892`. Commit `77df25e` allowed graph
generation to borrow unused upstream time, and `fdd70d1` reserved all remaining
repair and correction work. The staged pipeline in `8f061d0` bypassed that layer
with fixed generation timeouts. The new connection admission tests cover borrowed
time, the maximum call duration, downstream reserves, and preservation of the
approved graph when a stage cannot be admitted. Components keep the separately
enforced first-preview boundary.

### Complete full-corpus capture and batched follow-up

Run `34653111423` completed with 14 of 20 browser cases passing. Semantic evaluation
reported 12 passes, two cases for manual review, and six deterministic failures.
It recorded 75 provider attempts across 73 application operations and 14 judge
calls. Eight cancelled generation attempts lacked token usage. The known
application subtotal was $2.024380 and judge usage was $0.555010; total application
cost is unknown. The browser phase took 1,311.247 seconds. All artifacts were
downloaded, and their 90-day retention was verified.

| Case | Observed failure | Correction or evidence limit |
| --- | --- | --- |
| `rag-grounding` | Component scope rejected twice; no explanation after graph rejection | Explicit subject boundary; independent grounded answer after failed creation |
| `graph-expansion` | Four retained edge IDs changed during admission | Preserve baseline identities through normalization; shared identity owner for new edges |
| `applied-domain`, `architecture-controls`, `arbitrary-architecture` | Connection generation timed out twice | Borrow unused time within the absolute deadline and retain downstream reserves |
| `graph-renderability` | A second capability defect appeared after the first correction | Audit each capability against named ownership in the same review |
| `ambiguity` | A vague request triggered construction, then returned only rejection status | Structured clarification in the existing component call; no downstream generation or review |
| `memory` | Follow-up presupposed two ranked mitigations that turn one never requested | First prompt now explicitly requests two mitigations; human labels remain pending |

The expansion contained all twelve prior semantic connections and one addition.
The staged projector truncated relation slugs to 56 characters; the patch
normalizer regenerated them at 64 characters. Its locked-record check omitted
`edge_id` and `relation`. The captured graph reproduces this without model calls.
Baseline identities now survive unchanged endpoints and labels, and the validator
checks their values and presence. Authorized label or endpoint changes receive
new identities. A separate local probe found collisions for long, punctuation,
and Unicode labels. New edges now use one shared readable label plus digest in
both projection and normalization. Existing stored identities remain unchanged.

Local lifecycle checks reload the saved graph as JSON, add two components, and
remove the first addition. The original nodes, edges, and sequence remain exact.
Neighbor checks also found normalization clearing saved node `tier` and `detail`;
patch admission now retains those baseline-owned fields, including absence and
null values. New records keep their creation defaults.
Saved uppercase and long node IDs also survive edits unchanged. New IDs still
normalize and reserve existing IDs before resolving collisions, independent of
record ordering.

The failed-create response path now retains a truthful graph status while allowing
an independent grounded answer or clarification. Failed edits retain their exact
status without inventing another proposal. The component planner can return a
validated clarification result instead of a candidate, using its existing call.
The response is emitted directly without connection generation, reviews, or another
synthesis call. Ordinary replies to those questions can continue the design through
the existing router call and prior user context.
An independent three-turn replay caught dropped intermediate requirements. The
router now retains user constraints through the active design conversation and
stops at detected topic changes; assistant text cannot supply design authority.

A saved RAG screenshot exposed edge labels overlapping unrelated cards. Placement
now searches bounded positions in both dimensions and gives required labels
priority. An unplaceable label stays hidden even on hover; required-label coverage
still controls render admission. Real Chromium rendering of the saved RAG graph
shows all four required labels with no label-card or label-label overlap.
Screenshot review also found same-column return edges entering the far side of
their target and crossing its text. They now terminate at the near border. The
regression checks edge segments against source, target, and intervening cards.

All twenty semantic evidence packets passed the actual projection and prompt-size
checks offline. The largest was 48,697 characters against an 80,000-character limit.
Captured answer, book, and research text was preserved. This rules out packet
truncation as the cause of these failures.

### Follow-up staging evidence

Full run `34656915601` evaluates commit
`f1e1a7421e46a29fedb022da73c5d7ab70948974`. Its deployed revision
`agent-backend-staging-00375-sev` uses the staged pipeline and verified concurrency
of 16. A connection generation completed in 150.96 seconds, beyond the former
130-second cutoff. The RAG case corrected its initial scope, passed both gates,
and completed an answer with an approved eight-component graph.

The ambiguity and marketing traces then exposed the next deadline boundary:
connection reviews stopped at 54.93 seconds with incomplete usage and no final
output. The deployed reviewer uses a fixed 55-second timeout. Both graphs were
withheld; the failed-create response path still returned useful answers and
clarification. A shared staged deadline calculation now covers generation and
review in both phases, retaining baseline time for future attempts, synthesis,
and persistence. The first component preview keeps its own deadline.

The document-processing connection call completed in 198.90 seconds. Its exact
30-component, 95-edge candidate passed wire parsing and primary-flow reachability.
An offline Chromium replay and the actual backend render gate then rejected it:
only seven of eight required overview labels were visible. The missing label was
"ingestion receipt with source key". The renderer's fixed nearby search grid
missed a free position beside the node cards by 1.78 pixels. Free space existed;
the search did not cover it. The placement repair keeps successful nearby
positions and searches obstacle boundary coordinates only when the first search
fails. Required labels remain mandatory in the render gate.

The cold-chain candidate exposed a separate phase-ownership error. Component
generation selected the AI triage service as root even though sensor intake,
normalization, detection, and queueing were marked as upstream primary members.
Both connection attempts completed, taking 189.44 and 184.93 seconds, then failed
the same primary-flow reachability rule. The parser and projector agreed. Root
semantics were described only by the connection-stage logical-flow criterion,
after the component root and membership had been locked. The component-owned
objective criterion and creation prompt now define the initiating primary actor
and distinguish independent inputs from the primary path. Scoped edits retain
their existing root authority.

The expansion follow-up failed before any provider call because "the monitoring
component" matched both Monitoring Collector and Monitoring Dashboard. Exact
label controls each compiled a valid one-node, one-edge addition. The evaluator
accepted a connection to any monitoring node, while the product required one
identified target. The corpus now requests a component named Serving Monitor in
the first turn and explicitly expands that component in the second. Preservation,
addition count, and direct-connection checks remain mandatory. Ambiguous product
edits retain the approved graph and tell the user to repeat the edit with an exact
label or ID.

The completed run passed 15 of 20 browser cases. Semantic proposals contain 12
passes, three manual-review cases, and five failures. Application telemetry records
79 of 150 permitted provider attempts; three cancelled reviews lack complete usage.
The known application subtotal is $2.658481, not a complete run cost. Fifteen judge
calls cost $0.636020. All artifacts were downloaded with 90-day retention verified.
The manual-review proposals flag extra material in the RAG answer, a missed
one-paragraph constraint in the memory case, and disagreement about clarification
on the underspecified operations request. These are not clean semantic passes.
The judge and human labels were not changed to convert them into passes.

An independent deadline audit found no shorter wrapper around staged reviews.
The allocated timeout includes provider queue waiting; SDK and adapter retries
are disabled for these calls. The backend uses the same absolute deadline as the
budget calculation. Browser and Cloud Run deadlines are longer. Tests cover all
eight generation/review positions and admission failure before provider calls.

The ambiguity candidate also invented an IT operations domain in its assumptions.
Generation and review now distinguish implementation assumptions from missing user
goals. Retrieved examples cannot choose the user's business domain or workflow.
Clarification can replace correction of a candidate built around an invented goal.

An offline retrieval experiment used the cached embedding model and all twenty
first-turn corpus queries. Removing the literal book title improved this RAG
query's ranking, but lost the subject of an explicit question about the book.
Filtering frontmatter promoted irrelevant backmatter in that negative control.
Neither blanket change was adopted. The application still passes the full design
request to retrieval; there is no earlier subject-query model output being ignored.

PostHog's trace error count remained zero for the cancelled reviews. It cannot
establish successful graph publication. The captured graph operation and browser
result remain necessary evidence. Connector-rendered trace inputs can also contain
10,000-character truncation markers; those files are not complete raw prompts.

Five `/api/analytics/capture` requests received application rate-limit responses
under the shared evaluation account. These were not Cloud Run capacity failures.
The client drops failed mirrors, so product dashboard counts can undercount these
events. Chat state, graph publication, and server-side LLM usage accounting have
separate writers and were unaffected. Access logs do not identify the five event
payloads. The analytics delivery limitation remains outside this graph repair.

### Review boundaries and concurrent retries

The completed full run passed 16 of 20 browser cases. Semantic proposals had 13
passes, three manual reviews, and four failures. RAG, memory, and the exact Serving
Monitor expansion passed semantic review. The failures were marketing, document
processing, closed-loop evaluation, and cold-chain architecture. Complete usage
records account for 77 provider attempts and 16 judge calls: $2.504474 for the
application and $0.680132 for the judge. No incomplete usage was reported.

The full capture at `179c4d4451c437d3c3e417709d0f7c51d4327280`
([run 34659637747](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34659637747))
completed browser execution in 15 minutes 49.6 seconds. The shared deadline budget
allowed the marketing review to finish in 79.9 seconds and the document review in
61.7 seconds, beyond the former 55-second limit.

Both reviews then encountered a separate parser failure. An invalid route witness
caused the parser to discard eight valid marketing findings, two valid document
findings, and two closed-loop evaluation findings, then terminate without the
available correction. The parser now retains
validated semantic findings and the proof diagnostic. It accepts no malformed
proof and cannot approve that candidate. A malformed proof without valid semantic
findings still terminates. Review instructions distinguish contiguous route
witnesses from separate edges that demonstrate branches.

The marketing component review also rejected an optimizer that explicitly initiates
work by pulling evaluated outcomes. An offline witness preserved all 17 original
components and the optimizer root: adding the outward request to the existing
return response passed both connection parsing and graph projection. Removing the
request failed both checks. Root selection now recognizes declared pull behavior
without inventing requests for push-only sources.

The cold-chain component review demanded incoming edges for a recovery owner before
connection generation. Component review now assesses whether the declared
responsibilities support a feasible directed path. Missing edges or absent peer
names alone cannot reject a component plan. Actual directed reachability remains
mandatory when connections are generated and projected.

The document candidate exposed an upstream ownership gap. It enabled learning and
release but assigned regression-gated release only to a version registry. No
executable component owned offline evaluation. The connection stage could not add
that owner after component approval. Production component criteria now require
executable ownership for applicable mutation, reuse, and release obligations.
Compatible operations may share an existing owner; this does not require one
component per checklist item. Prototype criteria remain unchanged.

A separate offline transport audit reproduced a duplicate-request race with real
SQLite persistence. A competing instance completed after the early replay check
but before stream admission. The second instance recomputed a response, persistence
correctly deduplicated it, and WebSocket publication displayed the unsaved second
graph. Chat now serializes each thread independently of the per-user concurrency
limit and rechecks completed requests after acquiring both leases. The retry
replays the saved answer and graph without a model call. The same check applies
to SSE. Lease lifetime covers context reads, execution, persistence, and publication.

The concurrency review also checked cancellation and responses that never start
streaming. SSE acquires its leases inside the stream generator, so an unstarted
response owns no lease. Task cleanup failures must not skip WebSocket lease release.
These cases use deterministic transport tests rather than paid model reruns.

The domain-specificity rubric also conflicted with two corpus requests. It
penalized an explicitly educational tools-and-memory diagram for not inventing a
business use case, and an underspecified operations clarification for not drawing
an architecture. Corpus `2026-09-12.v1` / `browser-rubric-v3` now judges the stated
application or educational subject and permits targeted clarification of missing
requirements. Generic substitutions and vague questions still fail. Existing
human labels remain empty; model proposals are not human approval. The separate
long-context answer exceeded its explicit summary-only scope, so that manual
instruction-following finding remains valid.

### Deadline, traversal, and conversation ordering

The full run on `e982be12de391e8e30884f1033b7005cbabb5007`
([34661446928](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34661446928))
exposed two further generation failures. Its marketing component call stopped after
129.955 seconds with incomplete JSON; the retry received 9.798 seconds and returned no
text. The terminal workflow had reserved another attempt, but a separate 170-second
preview cutoff allowed only 140 seconds for all generation before the first render.
Both the generation helper and renderer enforced that cutoff.

Staged generation now uses the existing 240-second maximum and terminal reservations.
The preview target remains measurable without cancelling a recoverable staged request.
A fresh 910-second terminal window permits 147 seconds initially and 200 seconds after
that attempt times out, before orchestration overhead. Every remaining generation,
review, private render, synthesis, and finalization reserve remains intact. Legacy
preview deadlines and explicit browser latency assertions are unchanged. Regressions
exercise a late successful retry, a rejected private render, and a stalled render channel.

The closed-loop candidate placed an event bus outside the walkthrough but routed main
stages through it. The old parser required all intermediate nodes to be walkthrough
members. Primary membership now selects walkthrough nodes; reachability traverses all
accepted directed runtime/control contracts. Feedback and deployment edges cannot
establish that reachability. One function owns both parser and projection behavior.
Selected distance levels are renumbered consecutively for playback. The retained
25-edge correction passes structural replay; the earlier 28-edge candidate still
fails because its registry has no runtime/control path. Semantic review remains
required. Protected sequence metadata survives scoped edits, and changed review
identities invalidate prior approvals.

Two captured conversations also exposed reversed history: an assistant answer preceded
the user message it answered. Transaction timestamps do not order messages within a
turn. A database-generated message sequence now supplies an explicit order for both
model history and UI reloads. PostgreSQL uses an identity sequence with cache 1;
SQLite uses an explicit autoincrement key while preserving UUID message IDs. Existing
writers receive sequence values automatically. The additive PostgreSQL migration
restores known request pairs; it cannot recover the original chronology of historical
turns whose timestamps tie. Production migration and application promotion remain
separate release work.

A second source of unwanted design advice was deterministic routing. A request to
summarise deployment constraints was classified as a new design because it contained
"architecture". Shared clause classification now recognizes explanatory requests after
introductory clauses, while preserving independent explicit design/edit requests and
product-name seeds. This prevents that summary from forcing fresh retrieval. The
separate graph explanation prompt no longer requires a full walkthrough or three to
six blocks for a narrow follow-up. The streaming parser also stops adding empty
sections to reach a minimum block count; a valid focused answer can contain one block.
These changes remove concrete conflicts; the effect
of history ordering on model instruction compliance still needs live evaluation.

Failed graph operations now return their existing deterministic status and preserve any
prior approved graph. The removed failed-create model call could spend another 55
seconds inventing an unreviewed replacement design. Mixed explanation/design requests
now receive the failure status when graph creation fails. Independent explanatory
questions can be asked in a following turn. Timeout diagnostics distinguish timeout
from provider failure, and the internal evaluation export retains allocated time,
partial output size, error types, and nullable usage-completeness fields. Missing usage
is not reported as a free successful call.

## Validation and remaining release work

Focused regression suites and an independent replay of the retained graph passed.
All 11 offline groups pass after the stabilization changes: 1,769 backend tests at
91% coverage, 237 frontend tests, frontend lint/build/production dependency audit,
canonical artifacts, Python lint/security/dependency checks, migration compilation,
Terraform validation, container build, and 131 CI policy tests. The full command first
stopped on an obsolete assertion requiring the removed scheduled-evaluation success
bypass. That assertion was corrected; evaluation, whole-backend coverage, and all
remaining groups then passed. Earlier passing groups had no intervening source changes.
The retained graph replay and gate tests also passed after their final additions.

Commit `2803582ed2cb7747f02e88359b774e6ed6301e04` passed all 11 groups in one
canonical run: 1,833 backend tests at 91% coverage, 241 frontend tests, and 221
policy tests. Cloud CI passed the same groups. Its full 20-case protected staging
evaluation is [run 34653111423](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/34653111423).
Later named-addition, transport, and review-renderer fixes require their own final
validation and are not represented by that run's source identity.

Commit `971292d6e175ff7b7e3b9d1959f021661304ffdb` passed the next complete local
and cloud check runs: all eleven groups, 1,862 backend tests at 91% coverage,
243 frontend tests, and 221 policy tests.

Commit `5d08d336afe0be327fbc140eeb216d10119ec3d9` passed all eleven groups with
1,904 backend tests at 91% coverage, 243 frontend tests, and 237 policy tests.
That check includes capacity, deadline, and subject-boundary changes. The next
batched identity, clarification, recovery, and label-placement changes require a
separate complete validation and live capture.

Commit `f1e1a7421e46a29fedb022da73c5d7ab70948974` passed all eleven local and
cloud groups: 1,993 backend tests at 91% coverage, 246 frontend tests, and 237
policy tests. All 362 committed file contents matched the unchanged local test
snapshot. Eight saved Chromium renders had no sampled edge/card intersections,
node overlap, clipping, or visible label collisions. The shared deadline and
clarification refinements require their own validation after this commit.

Commit `179c4d4451c437d3c3e417709d0f7c51d4327280` passed all eleven local and
cloud groups: 2,065 backend tests at 91% coverage, 249 frontend tests, and 237 policy
tests. All 363 committed source blobs matched the unchanged local test snapshot.
The captured 30-node, 95-edge document graph showed all eight required labels and
passed the unchanged render gate. The review-boundary and concurrent-retry repairs
above require their own complete validation and live capture.

Existing optional ingestion tests remain skipped without the source PDF or model
opt-in. Dependency deprecation warnings, the local Node storage warning, and two
existing unmatched Bandit suppression warnings remain. The frontend lockfile's
`fflate` dependency was updated from 0.4.8 to 0.4.9 to clear the configured
production dependency audit.

The initial stabilization retained `GRAPH_PIPELINE_MODE=legacy`. After the successful
graph behavior in the fresh staging experiment, the candidate's applied-graph
default changed to `staged`; production has not been promoted. Full-corpus evaluation
must validate the final candidate, and the corpus still requires human review.

Pure group/sequence edits and mixed deletion-plus-edge-field updates remain outside
the current scoped delta contract. Future support must add explicit operation
authority rather than restoring whole-graph generation. Semantic review still
checks the assembled candidate and can reject it; the historical audit cannot
prove that every future disagreement will be correct.

## Worktree reconciliation

The three folders are worktrees of one repository. The implementation changes are
in `Agent` on `feature/staged-graph-pipeline`; the two older worktrees remain clean.
The merge-identity fix `9c26cde` in `Agent-live-eval-parallel` is patch-equivalent to
integrated commit `c4c583f`. Completed evaluation and graph fail-path work from
`Agent-eval-research-security` is represented by squash commits `648ee56` and
`77df25e` and subsequent changes.

That research branch also contains unfinished source-contract work in `aa44108`.
Its schema declares pinned sources and hostile evidence markers, but its browser
runner never enforces them. It was not cherry-picked. The current research-based
`instruction-conflict` case does not prove that hostile retrieved instructions were
encountered; corpus review should address that limitation separately.

## Collection and classification

The audit requested up to 400 runs for each workflow and exhausted the returned
history: 161 `Scheduled evaluation` runs from July 19 through September 11, and
230 `Live eval required` runs from July 18 through August 20. Twelve live-workflow
reruns bring the total to 403 attempts across 391 distinct runs. All run/job/step
metadata was downloaded. Logs were downloaded for all 179 runs that started the
browser-capture step, plus the 12 earlier attempts of rerun workflows.

The repository artifact API returned 319 artifacts with scheduled/live evaluation
names. Thirty-six were retained and downloaded, including replay copies; 283 were
marked expired. The retained files cover 17 completed failure captures and one
cancelled setup. Replay copies are not counted as additional executions.

The primary inventory is local and ignored by Git:

- `artifacts/failure-audit-2026-09-11/run-inventory.json`: all 403 attempts.
- `artifacts/failure-audit-2026-09-11/graph-expansion-55-failures.json`: all 55 rows,
  exact heads, GitHub links, primary evidence paths, failure details, costs, and
  explicitly labeled secondary documentation.
- `artifacts/failure-audit-2026-09-11/runs/<run-id>/`: jobs, downloaded logs, and
  retained result files.
- `artifacts/failure-audit-2026-09-11/{artifact-downloads,log-downloads,summary}.json`:
  collection coverage and counts.

In the table, `Product observation` means the retained evaluator reports a blocking
`quality` failure. It is not a claim that provider or infrastructure faults were
excluded as causes. `Unknown` means the commands failed but primary evidence cannot
classify the underlying defect. `B/S failed` means both logged outcomes are
`failure`. `Secondary` links the previous ledger and is not independent validation.
All rows have downloadable logs saved locally; a green GitHub conclusion does not
change the recorded failure.

## All 55 single-case failures

| UTC start | Run / exact source head | Observed class | Primary observation | Result artifacts | Secondary ledger |
| --- | --- | --- | --- | --- | --- |
| 2026-08-08 01:39:11 | [31233156283](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31233156283)<br>`d034a1de982e854c0d0f6fe3543fa43336b522a2` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 03:11:06 | [31236639491](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31236639491)<br>`15cb03a5c7f5d9c6ea4aeb0baad316b75dde55bb` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 07:33:32 | [31246433859](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31246433859)<br>`bf8180d401fc2f3793c719c3b93fbeb70016d797` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 09:09:37 | [31249964798](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31249964798)<br>`d474b4062e7a50cc500b1b5c8086e65b5750c7ae` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 10:33:04 | [31253023919](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31253023919)<br>`81a090e04c380eedee80da1fea7ea29f826b36d3` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 11:34:41 | [31255291000](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31255291000)<br>`41f488108b7b88312e97947d9091e15ccdadc3bc` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 11:44:24 | [31255655951](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31255655951)<br>`41f488108b7b88312e97947d9091e15ccdadc3bc` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 12:18:15 | [31256929226](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31256929226)<br>`e645bf242704d7b16a9eb3f5335dfd55c1dc614f` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 12:41:24 | [31257810429](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31257810429)<br>`122b1fd399eb23297b022c32191fc69229cdbf3e` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 13:25:00 | [31259489721](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31259489721)<br>`93bc29bc8d0da7ccf9d408c38e36945826cb0554` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 14:13:11 | [31261404727](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31261404727)<br>`bf3bde1324bd717fa00fc487411106ccc2b1d3a0` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 14:34:36 | [31262285743](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31262285743)<br>`3c2ceaa025bffd8ed02d2b6cc3d9f909e8f284c4` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 14:52:54 | [31263053030](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31263053030)<br>`84f628f000f83482eaf077b95b7098babf2962a4` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 15:23:48 | [31264351143](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31264351143)<br>`1ac7ac7f6be6a2815b83e31fbb2291a8b52c4d91` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 16:20:32 | [31266712755](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31266712755)<br>`4ae22cb9429c6b3d57ec60b35664c40f3fe4a06b` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 17:19:47 | [31269147909](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31269147909)<br>`0fdabf0e19c3f9a2e3cd03df884ef446ac73513e` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-08 17:46:00 | [31270244823](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31270244823)<br>`a3dd810c759ca1c276638ae771d97498b5140f0a` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-09 14:56:28 | [31319775700](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31319775700)<br>`d332cb08dc2cf8a42669838e6b23f70d96e9ece5` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-09 16:13:14 | [31323209766](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31323209766)<br>`aa57465991baa9d795bac1dadba1b3edb3b07039` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-09 17:22:26 | [31326225204](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31326225204)<br>`81a3cc13d11cb723c2b2e7e59800e563369456a0` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-09 19:59:17 | [31333075986](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31333075986)<br>`2f88a5a244265d7e9e94e497d096e3397ed10d87` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-09 20:53:59 | [31335429802](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31335429802)<br>`b2bd76abd7af2fd52d93b3e6c53c6006bfddb9fc` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-09 22:40:57 | [31340006983](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31340006983)<br>`7ce69b617e93665c0b6536c7903363e67b9ad27a` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-10 08:16:39 | [31369358742](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31369358742)<br>`77df25e7dc6402714e86562e3d9658f653a7a4dd` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-10 09:17:16 | [31373878762](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31373878762)<br>`017f7d07d269f1e06a3af21a0fc4fec7faf63f46` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-11 18:38:41 | [31523789373](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31523789373)<br>`9a3dcd2d91ab33fbb246a4761f8b7d6c70cb9808` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-11 23:46:57 | [31547774792](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31547774792)<br>`67887c3ebd89ebaec2db268e91927f8f3697a2d5` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 00:08:09 | [31549117335](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31549117335)<br>`1a279b67e997426003aeb913ef28e6fa4e4c0cae` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 00:16:55 | [31549644038](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31549644038)<br>`b64f66f3ac6b157840277133a1a6ae516cd8d07a` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 10:46:49 | [31588931923](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31588931923)<br>`ca8e3b2ad6038a838870e5fad6959c595c40fe16` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 12:48:17 | [31598216294](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31598216294)<br>`ccd5c7712323be5d3fc47f304b03d92fd28e7498` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-12 15:09:59 | [31610799035](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31610799035)<br>`fd61175d7ddb627ea9bed203588b756c0cfa5c6f` | Unknown | B/S failed; specific cause unavailable | Expired | Absent |
| 2026-08-12 15:24:57 | [31612168038](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31612168038)<br>`ad82144fa48f5b6fd498b55b69384a279cb6650a` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 15:51:46 | [31614596529](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31614596529)<br>`5a3b5f1a21458964f95eee6405e8b74b50c6692e` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 16:18:41 | [31616927365](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31616927365)<br>`5c9b27589a29aef90d77571f993a37ab089fa6ce` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 16:54:05 | [31619916923](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31619916923)<br>`ae916b32818ea752e2cd6e46d4bcb31d69b1f025` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 17:44:42 | [31624156649](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31624156649)<br>`7767994733dd222b07c6278a87032b086dcf2326` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-12 20:28:26 | [31637814841](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31637814841)<br>`f15537a3270b4d0e2d011f14fe4cfddf033e389b` | Unknown | B/S failed; specific cause unavailable | Expired | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-13 13:37:58 | [31705887318](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31705887318)<br>`30c8a5418ce5479c9e5cea170a574355a99608a8` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-14 08:42:48 | [31785036626](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31785036626)<br>`4b2b7f261e689322f76611d8654c6a6e7aec4539` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-14 11:36:55 | [31796931744](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31796931744)<br>`b098cc59af0c329ec28cb4654faa08b5711d7a8d` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-14 17:45:07 | [31825436257](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31825436257)<br>`a2e7766e295590c558145ef2f69a2abfb5bb644b` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-15 11:19:39 | [31881756822](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31881756822)<br>`4c2bae8ff12c3204fb3b492cbf27210cfec9542b` | Product observation | `required_graph_version_reused` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-15 17:19:45 | [31897989519](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31897989519)<br>`f181e855987d286ddf66f04e35c0ea30a86005f0` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-15 18:20:48 | [31900871827](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31900871827)<br>`4faf04de329e3d9934a3363ea475c6a8d19dcf94` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-15 19:08:43 | [31903086208](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31903086208)<br>`f045abf31f6164f3d2e6f3567d026645c2dfb52e` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-16 09:36:38 | [31939496092](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31939496092)<br>`06dac4e2946d6e26b949c396317765a46e798a8d` | Product observation | `graph_expansion_added_node_count_mismatch` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-16 14:38:39 | [31953303244](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31953303244)<br>`54bb8acc6ae40ba4411a5c3f9f35a684c6f04c1f` | Product observation | `graph_expansion_added_node_count_mismatch` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-16 21:18:03 | [31973080544](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31973080544)<br>`8f061d00cf12b7edc04da3533cb7dad49d3c3f59` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-17 08:15:31 | [32009504451](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32009504451)<br>`e35c521071d1945c3d7ee44428706774ace6d222` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-17 18:24:21 | [32054742321](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32054742321)<br>`3b1ad90547ef76ee13e9d81caefe43de0b6b5374` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-19 19:07:01 | [32291218614](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32291218614)<br>`be98b79d1683b44025e29e3bda2a37359321d8fa` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-19 19:48:10 | [32295031180](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32295031180)<br>`5e73e121fd4aafd6023762897259a52a79a9a310` | Product observation | `required_graph_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-19 20:30:21 | [32298885657](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32298885657)<br>`c84915c1c2f44e7079780074ddbed6aac64a4ada` | Product observation | `graph_expansion_prior_assumption_missing` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |
| 2026-08-19 20:49:44 | [32300653373](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32300653373)<br>`8efaaf957ff01676377db9bf10a96ba68de626d9` | Product observation | `required_graph_version_reused` | Retained | [Secondary](eval-stabilization-intermediate.md#recent-diagnostic-failure-ledger) |

## Other workflow executions

Counts below include reruns and are mutually exclusive. A started browser step
alone does not establish that a paid provider call occurred.

| Execution evidence | Scheduled | Live required | Total |
| --- | ---: | ---: | ---: |
| Paid failure verified by retained artifact | 17 | 0 | 17 |
| Failed evaluation outcome; paid usage unverified | 65 | 62 | 127 |
| Cancelled after browser step started | 8 | 7 | 15 |
| Recorded successful evaluation outcome | 9 | 2 | 11 |
| Browser started; final outcome unknown | 9 | 0 | 9 |
| Cancelled before browser step | 38 | 101 | 139 |
| Pending-corpus work skipped | 0 | 67 | 67 |
| Failed before browser step | 13 | 2 | 15 |
| Unfinished without browser step | 2 | 1 | 3 |

Four failed mixed-case diagnostic executions also selected `graph-expansion`:
`30760765158`, `30996877768`, `30999068051`, and `31001260035`. Their aggregate failed
outcomes do not establish which selected case failed, so they are excluded from the
55 single-case failures.

Single-case `graph-expansion` run
[`31241232161`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31241232161)
on August 8 records successful browser and semantic outcomes. Its expired capture
prevents independent review of its graph quality, corpus version, and paid usage.
Seven other single-case captures were cancelled and are not counted as completed
failures.

Fifteen attempts failed before browser execution. Their failing setup, approval, or
classification steps are recorded in the machine-readable inventory; they are not
counted as paid product failures. The 67 pending-corpus skips likewise provide no
live product evidence.

## Evidence limits

The 55-row count is a count of independently verified failed diagnostic executions,
not 55 independently reconstructed model failures. Only 17 retain enough primary
result evidence to prove paid calls and inspect the failed product assertion.
Current source, old commit messages, and the previous ledger cannot recover missing
candidate outputs, provider usage, or review decisions for the remaining 38.

The audit records observed outcomes and evidence gaps. It does not certify the
current fixes, establish that every historical root cause remains reachable, or
supply the corpus approval required for protected evaluation.
