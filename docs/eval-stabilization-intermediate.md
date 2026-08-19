# Live Evaluation Stabilization: Intermediate Record

Last updated: 2026-08-19

Evidence in this record is current through paid diagnostic `32298885657` on
`feature/staged-graph-pipeline` on 2026-08-19. PRs #37 through #40 merged on 2026-08-07, and PR #44
merged as `77df25e7`. The evidence-provenance, graph-review, and latency corrections passed local
review and the full offline CI matrix through the raw staged edit-scope fix. Thirty-one consecutive
recent `graph-expansion` diagnostics have failed; there is no protected live success on
the current branch.

Diagnostic `31953303244` invalidates the Release 1 live prerequisite for the legacy repair loop.
It made 13 application calls, cost $1.166855, and took 752.114 seconds. Turn 1 published 14 nodes
and 19 edges. Turn 2 created a 15-node candidate, then the final connections contract failed
`invalid_contract` and restored the 14-node graph. A final whole-graph repair gate cannot be the
release path when it discards a candidate that satisfied the requested expansion.

The staged state machine is available behind a feature flag. The legacy repair loop remains the
default and rollback path. Each staged layer admits at most two generated candidates.
Corpus `2026-08-12.v1` remains pending human review.

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
`c84915c1c2f44e7079780074ddbed6aac64a4ada`. Every
row records a live product failure. A green workflow conclusion for a report-only row means the
pending-corpus workflow uploaded its evidence and exited without enforcing the failed verdict. The
initial workflow runs failed; later report-only diagnostics concluded green under that policy.
The retained `live-results.json` for every row says `status: fail`. The first nineteen failures ended
on turn 1 and skipped turn 2. Five of those failures emitted a reversible preview without an
authoritative graph; the other fourteen emitted no visible graph. The twentieth failure published
turn 1, reached turn 2, previewed a fresh expansion candidate, and then restored the approved turn 1
graph after repair rejection. The twenty-first failure ended on turn 1 after previewing two fresh
candidates and withholding both after semantic review. The twenty-second failure previewed one
fresh candidate, rejected an impossible patch contract, and timed out during its corrected retry.
The twenty-third failure rendered three private candidates, consumed two semantic repair rounds,
and withheld the graph. The twenty-fourth published turn 1, previewed the requested turn 2
expansion, and restored turn 1 after a repaired private render inherited the expired initial-preview
deadline. The twenty-fifth published a 14-node graph on turn 1, created a 15-node turn 2 candidate,
and restored turn 1 after the final connections contract failed `invalid_contract`. The twenty-sixth
passed its first staged component render, then failed correction admission before a second render.
The twenty-seventh passed component review and three private renders, then withheld turn 1 after
two connection-review rejections. The twenty-eighth produced a complete eight-edge model-serving
candidate, then a generic correction added an undeclared monitoring-to-gateway control edge. The
second connection gate rejected that exact edge and withheld turn 1.
The twenty-ninth passed deployment, readiness, and browser smoke checks. Both component candidates
passed private rendering, then failed the component gate before connection generation. The first
candidate failed `brief_coverage`, `independent_risk_coverage`, and `objective_fidelity`; the second
failed `brief_coverage`. The generator had only the request while the gate also had the canonical
evidence frame.
The thirtieth produced a concise five-component serving stack. Its first component gate rejected
one serving responsibility for `capability_classification`. The correction removed the ambiguous
retrieval claim and added an explicit no-retrieval assumption. The second gate then introduced an
`independent_risk_coverage` blocker even though the staged route has no upstream reviewed-risk
artifact.
The thirty-first passed both staged gates on both turns and published the requested turn-two
expansion. It preserved the title, all seven prior nodes, all ten prior edges, the sequence, and prior
group records. It added one directly connected monitoring node. The generated component frame
replaced all five prior assumption strings, so the exact graph-expansion preservation check failed.
Run links and recorded heads come from GitHub Actions metadata. Latency, provider calls, failure codes,
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
| 2026-08-12 00:16 | [`31549644038`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31549644038), `b64f66f` | A valid architect plan took 78.784 seconds and Kimi took 81.252 seconds. Deterministic topology validation rejected `connections.links[6]` before private render, preview, or Sonnet. Three calls ran; turn latency reached 180.083 seconds. | The topology wire contract now has one zero-based representation. Links, parents, groups, and sequence members use the same direct indexes. | at least $0.232051 |
| 2026-08-12 10:46 | [`31588931923`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31588931923), `ca8e3b2` | The architecture boundary rejected `evidence_basis[8].evidence_ref` under the private rule `invalid_engineering_area`. Two calls ran; the turn took 107.735 seconds and the case took 109.568 seconds. No Kimi, private render, critic, turn 2, or fallback ran. | Removed engineering recommendations from model-facing evidence. Checklist guidance now belongs in decisions or assumptions, and legacy model rows are discarded without weakening book, web, or user provenance. The green wrapper was report-only; the correction is not live-proven. | $0.236575 |
| 2026-08-12 15:24 | [`31612168038`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31612168038), `ad82144` | Kimi low returned a complete topology in 24.530 seconds on one attempt. Deterministic validation rejected `composition.steps[3][0]` because the model's sequence order conflicted with its directed tree. No preview, render, architecture review, semantic review, or turn 2 ran. Fallback synthesis completed after rejection. The case took 61.025 seconds. | Sequence batches now select membership only. The server derives stages by breadth-first traversal from the root across selected tree and runtime edges. Missing-root, duplicate, invalid, and unreachable selections still fail closed. | $0.082805 |
| 2026-08-12 15:51 | [`31614596529`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31614596529), `5a3b5f1` | Kimi low produced a valid seven-node graph. Topology validation and private rendering passed, and the reversible preview appeared after 37.228 seconds. Initial Sonnet review and its one protocol correction both returned successfully, but the corrected canonical contract retained `group_ids` without authorized `groups` authority. Review failed at `layers.composition.group_ids: invalid_contract`; the preview was withdrawn, turn 2 was skipped, and the case ended after 289.826 seconds. Five calls ran without provider fallback. | Canonicalization now filters group IDs, sequence indexes, assumption indexes, and their append counts through the server-authorized composition fields as one atomic permission profile. | $0.426546 |
| 2026-08-12 | [`31616927365`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31616927365), `5c9b27589a29aef90d77571f993a37ab089fa6ce` | The run retained a ten-node, thirteen-edge graph and emitted a reversible preview after 24.116 seconds. Private rendering passed, but semantic review failed with `semantic_review_protocol_invalid` at correction `critic_scorecard: invalid_contract`. Final `graph_data` was `null`; turn 2 was skipped. Five application calls ran without fallback. The turn took 263.485 seconds and the case took 265.625 seconds. | Preflight now checks the exact root scorecard shape and emits `critic_scorecard: invalid_shape`. Nested contract defects retain their leaf coordinates. A failed server-canonical invariant emits `canonical_review: invalid_server_state` and skips model correction. | $0.457343 |
| 2026-08-12 | [`31619916923`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31619916923), `ae916b32818ea752e2cd6e46d4bcb31d69b1f025` | Kimi returned complete JSON, then deterministic validation rejected the sixth component parent at `components[5][0]: topology`. No graph, preview, private render, critic, or turn 2 ran. Two application calls ran without fallback. The turn took 52.083 seconds and the case took 54.158 seconds. | Removed the selectable index base and nested sequence batches from the internal topology wire format. Every reference is zero-based, sequence membership is one flat list, the prompt gives the exact late-row bound, and safe logs retain the observed and maximum parent indexes. | $0.074490 |
| 2026-08-12 | [`31624156649`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31624156649), `7767994733dd222b07c6278a87032b086dcf2326` | Kimi produced a valid nine-node, thirteen-edge zero-based graph. Private rendering passed and a reversible preview appeared after 76.944 seconds. The architecture audit found wrong and duplicated edges plus an incomplete sequence. Sonnet completed one review call, but the server rejected its canonical repair contract at `canonical_review: invalid_server_state`; final `graph_data` was `null` and turn 2 was skipped. Four application calls ran without fallback. The case took 261.184 seconds. | Canonical repair-contract failures derived from untrusted scorecards now enter the existing bounded protocol-correction lane. Server-owned failures introduced after locked-layer merging still fail closed without retry. The prompt requires an exact existing selector or exact addition for every blocking components or connections row. | $0.388656 |
| 2026-08-12 | [`31637814841`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31637814841), `f15537a3270b4d0e2d011f14fe4cfddf033e389b` | Kimi low returned complete JSON in 28.923 seconds. Deterministic topology validation rejected `components[5][4]` because its group index did not reference a defined `composition.groups` row. No graph, preview, private render, critic, correction, or turn 2 ran. Two application calls cost $0.082446, and the case took 64.963 seconds without retry or fallback. | The model-facing wire now puts `group_label` and `group_kind` in every root and component row. `composition.groups` and all membership indexes are removed. The server derives canonical groups from the inline identity and retains bounded-label collision checks. Initial Kimi effort is `high`; literal `medium` remains unsupported by the adapter. | $0.082446 |
| 2026-08-13 | [`31705887318`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31705887318), `30c8a5418ce5479c9e5cea170a574355a99608a8` | Kimi high returned a valid 11-node, 21-edge candidate in 131.559 seconds. Topology validation and private rendering passed, and a reversible preview appeared after 134.684 seconds. Opus completed its audit. The first Sonnet critic request then failed before stream acceptance with provider error `overloaded_error`; it had zero tokens and no deltas. Final `graph_data` was `null`, turn 2 was skipped, and no fallback ran. Four application calls cost $0.295396; the case took 250.153 seconds. | At that head, critic calls allowed one retry inside the existing stage deadline for retryable failures before `message_start`. The current workflow supersedes that behavior and permits one provider attempt per budgeted critic dispatch. | $0.295396 |
| 2026-08-14 | [`31785036626`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31785036626), `4b2b7f261e689322f76611d8654c6a6e7aec4539` | Kimi high returned a valid 10-node, 20-edge grouped prototype. Private rendering passed and a reversible preview appeared after 126.216 seconds. The initial Sonnet scorecard and its single correction both completed, then failed at `correction / critic_scorecard / invalid_contract`. Final `graph_data` was `null` and turn 2 was skipped. Five application calls completed on their first provider attempt without fallback. They cost $0.454679; the turn took 342.913 seconds and the browser case took 345.162 seconds. | Grouped prototype component additions required composition group authority, while prototype canonicalization treated the only group-oriented rubric as advice and stripped its selectors. The server now derives a structural composition blocker only beside a blocking component addition and exact connection obligations. It retains only cited existing groups or the declared group append count and returns typed missing-authority coordinates. | $0.454679 |
| 2026-08-14 | [`31796931744`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31796931744), `b098cc59af0c329ec28cb4654faa08b5711d7a8d` | Kimi K3 high made one provider attempt and returned in 63.017 seconds of telemetry, 62.961 seconds at the provider, costing $0.039297. Deterministic validation rejected `graph_design_topology_invalid` at `components[4][0]`: observed parent index 5 exceeded maximum 4 and self-parented. No preview, graph, fallback, or turn 2 ran. Opus low synthesis completed in 27.946 seconds and cost $0.064554. Total application cost was $0.103851; the turn took 94.212 seconds and the browser case took 96.242 seconds. The report-only workflow succeeded, but the evaluation failed. | One bounded error-informed complete-topology correction now runs within the same stage deadline with the same Kimi high effort, a distinct prompt, and one provider attempt. It then stops for validation. The next paid run produced a valid first candidate, so this correction branch remains live-unexercised. | $0.103851 |
| 2026-08-14 | [`31825436257`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31825436257), `a2e7766e295590c558145ef2f69a2abfb5bb644b` | Kimi high returned a valid ten-node, fifteen-edge candidate. Initial topology validation passed, so the topology correction was not exercised. Private rendering rejected the candidate with `overlap_count=1` and `minimum_text_px=9.401850585937499`, below the 11-pixel floor; `clipped_nodes=0` and `clipped_edges=0`. No graph preview, semantic critic, repair, fallback, or turn 2 ran. Two application calls cost $0.095151, and the browser case took 86.960 seconds. | The model does not own layout. The renderer now chooses from actual fit scale, sizes bottom lanes by cardinality, and falls back to a rank-ordered compact plan covering the 60-node safety ceiling. The server sends the render criteria. The exact candidate passes local Chromium with zero overlap or clipping and 14.68-pixel titles. Paid verification remains pending. | $0.095151 |
| 2026-08-15 | [`31881756822`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31881756822), `4c2bae8ff12c3204fb3b492cbf27210cfec9542b` | Turn 1 published a ten-node graph after one repair. Turn 2 produced an eleven-node candidate, passed private render, and failed semantic repair. The initial Sonnet scorecard needed a protocol correction. Kimi then returned an invalid patch with an added edge outside the new-component scope. The consumed shared correction slot prevented the error-informed contract correction, so the workflow restored turn 1's graph and failed `required_graph_version_reused`. Twelve calls ran without fallback. Case latency was 727.200 seconds. | Protocol-format and patch-contract corrections now have separate counters under the four-call critic ceiling. The next run exercised the contract-correction lane and exposed the deeper mixed-edge validator contradiction recorded below. The current fix removes that redundant rule. | $1.102968 |
| 2026-08-15 | [`31897989519`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31897989519), `f181e855987d286ddf66f04e35c0ea30a86005f0` | Turn 1 produced a nine-node candidate, corrected one scorecard ownership error, repaired it into a fourteen-node candidate, and passed private rendering for both. The post-repair scorecard marked two prior context blocker IDs `still_fail` after their exact identities had changed. Server validation rejected `prior_obligation_dispositions must match server-derived typed blockers`, publication returned `graph_data: null`, and the evaluator failed `required_graph_missing`. Seven one-attempt calls cost $0.611650. Case latency was 497.341 seconds, with the first preview after about 70 seconds. | Prior obligation dispositions are no longer model output. The server compares current typed blocker IDs with prior blockers and derives every resolved or still-failing status. The safe coordinate mapper retains `prior_obligation_dispositions` for any internal invariant failure. | $0.611650 |
| 2026-08-15 | [`31900871827`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31900871827), `4faf04de329e3d9934a3363ea475c6a8d19dcf94` | A five-node, seven-edge candidate passed private rendering and emitted a preview after 68.077 seconds. Sonnet authorized four new nodes and nine exact edges, including `n3 -> n5` between existing nodes. Kimi completed the patch in 191.651 seconds, then the global new-component edge rule rejected that required edge. The contract correction retained the same contradiction and expanded the repair to seven nodes and fourteen edges. The retry was cancelled after 132.459 seconds, 1.192 seconds after its first text delta. Final `graph_data` was null; the case took 633.072 seconds. Seven calls ran without fallback or judge calls. One accepted Kimi call retained no terminal usage. | Exact connection obligations now own every added edge. Mixed new-component and existing-to-existing additions are permitted only when their source, target, and normalized label are cited. New-node attachment, graph anchoring, locked records, and post-normalization checks remain. | at least $0.440616 |
| 2026-08-15 | [`31903086208`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31903086208), `f045abf` | The workflow wrapper reported success while the product withheld turn 1. Kimi high produced a private preview in 39.982 seconds. Private renders passed for candidates 8/11, 13/20, and 13/22. Sonnet medium rejected components once, then `edge_semantics` twice. The two successful semantic repair rounds were exhausted, so `graph_data` was withheld and turn 2 was skipped. Eight calls ran in 363.588 seconds with no fallback. | Prototype scorecards now exclude architect diagram requirements. Existing-edge repairs must declare exact update, remove, or replace operations. The reviewed graph snapshot remains paired with each scorecard. Safe internal diagnostics record the selected depth, locks, findings, blocker IDs, fingerprints, and correction outcomes. | $0.515946 |
| 2026-08-16 | [`31939496092`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31939496092), `06dac4e2946d6e26b949c396317765a46e798a8d` | Turn 1 published a seven-node graph in 143.111 seconds and previewed it after 39.179 seconds. Its prototype parallel path called Sonnet twice. Turn 2 previewed the requested eight-node expansion after 25.259 seconds. Production review rejected it, Kimi completed one semantic repair, and the repaired private render failed `diagram_evaluation_timeout` because the 170-second first-preview deadline had already expired. The workflow restored turn 1, so the evaluator reported `graph expansion added 0 nodes; expected 1`. Ten calls ran without fallback or judge calls. The case cost $0.764855. | The parallel-review marker is now declared in `AgentState`, so LangGraph retains it and routes an approved prototype scorecard past a second critic call. Private rendering and preview transport consult the first-preview deadline only during repair round zero. Focused tests and the full offline matrix pass; paid verification remains pending. | $0.764855 |
| 2026-08-16 | [`31953303244`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31953303244), `feature/staged-graph-pipeline` | Turn 1 published 14 nodes and 19 edges. Turn 2 created a 15-node candidate. The final connections contract failed `invalid_contract`, so the workflow restored the 14-node turn 1 graph. Thirteen application calls ran. The case took 752.114 seconds. | This invalidates the Release 1 live prerequisite for the legacy whole-graph repair loop. Release 1 changes to the flag-gated staged state machine described below. | $1.166855 |
| 2026-08-16 | [`31973080544`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31973080544), `8f061d00cf12b7edc04da3533cb7dad49d3c3f59` | The staged component preview contained seven nodes and passed private rendering after 58.441 seconds. Sonnet rejected the component layer. A second Kimi call completed, then the correction failed before its private render. The workflow discarded the validation coordinate, withheld turn 1, and skipped turn 2. Four calls ran without fallback. The case took 148.950 seconds. GitHub Actions reported success despite the failed live gate. | Corrections now receive the rejected component or connection candidate. Provider schemas share the server's text limits and reject empty components, invalid roots, duplicate identities, self-loops, duplicate edges, and unreachable primary flows. Safe diagnostics retain the stage, attempt, code, path, and fingerprints. Manually dispatched diagnostic failures now fail the Actions job. Paid verification remains pending. | $0.138016 |
| 2026-08-17 | [`32009504451`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32009504451), `e35c521071d1945c3d7ee44428706774ace6d222` | The component candidate passed review. Initial and corrected connection candidates contained five and seven edges; all three staged candidates passed private rendering. The correction added the inference response route while retaining a dangling model-artifact fetch. Sonnet rejected both connection candidates, `graph_data` was withheld, and turn 2 was skipped. Seven calls took 202.830 seconds without fallback or judge calls. The workflow failed closed. | Prototype staged review now excludes `logical_flow` and `branch_completion`, which the authoritative rubric marks advisory at that depth. Connection prompts require reverse response edges for synchronous reads and completion of supporting branches. Final gate exhaustion retains a safe scorecard diagnostic instead of discarding its rule codes and record paths. Paid verification remains pending. | $0.198687 |
| 2026-08-17 | [`32054742321`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32054742321), `3b1ad90547ef76ee13e9d81caefe43de0b6b5374` | The component gate passed. The first connection candidate contained complete request, response, model-artifact return, and telemetry-storage paths. Its correction added `Monitoring Service -> API Gateway` as an asynchronous control edge. The final gate rejected `connections.8` for `edge_semantics` and `safe_action_boundary`. All private renders passed, then the workflow emitted `graph_data: null`. Seven calls took 192.767 seconds end to end, cost $0.200053, and used no fallback or judge calls. | Connection generation and review now receive the locked component responsibilities, assumptions, types, and capabilities. Observation-only runtime completeness accepts a durable telemetry sink. A create correction cannot introduce a control edge unless a locked endpoint owns a `control` or `decision` role. Internal evaluation evidence retains each rejected gate attempt. Paid verification remains pending. | $0.200053 |
| 2026-08-19 | [`32291218614`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32291218614), `be98b79d1683b44025e29e3bda2a37359321d8fa` | Deployment, readiness, and browser smoke checks passed. The first seven-component candidate failed `brief_coverage`, `independent_risk_coverage`, and `objective_fidelity`. Its thirteen-component correction still failed `brief_coverage`. No connection call ran, `graph_data` was null, and the case cost $0.187481. | Component generation and review now receive the same bounded formatted evidence frame. The context excludes internal evidence IDs, treats source records as untrusted data, keeps selected maturity authoritative, and states that checklist questions do not each require a component. Paid verification remains pending. | $0.187481 |
| 2026-08-19 | [`32295031180`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32295031180), `5e73e121fd4aafd6023762897259a52a79a9a310` | The first five-component candidate failed only `capability_classification` on the serving service. Its correction removed the ambiguous retrieval claim and added an explicit no-retrieval assumption. The second gate then rejected `independent_risk_coverage` on the serving service, model API, and monitoring service. No connection call ran. The browser case took 110.289 seconds and cost $0.145035. | The staged component gate no longer exposes `independent_risk_coverage`, whose contract requires an upstream independently reviewed risk artifact. The canonical rubric and full-graph review retain the rule. The two-candidate bound remains unchanged. Paid verification remains pending. | $0.145035 |
| 2026-08-19 | [`32298885657`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/32298885657), `c84915c1c2f44e7079780074ddbed6aac64a4ada` | Both component gates and both connection gates passed. Turn 1 published seven nodes. Turn 2 kept those nodes and added `n8`, but replaced all five prior assumptions with six production-oriented assumptions. The evaluator failed `graph_expansion_prior_assumption_missing`. Ten one-attempt application calls cost $0.386631; no fallback or judge call ran. | Deterministic staged edit authority now compiles from the raw user message. The contextualized retrieval query remains model-facing. A production-depth expansion regression proves local scope and exact preservation of prior assumptions. Paid verification remains pending. | $0.386631 |

Known application spend across these thirty-one failures is at least **$11.031519**. Several provider
calls have incomplete usage; row amounts marked `at least` are lower bounds. Diagnostic
`31549644038` retained only `connections.links[6]: topology`; it did not retain authored output and
cannot distinguish an out-of-range endpoint from a self-link.

Head `fdd70d1` passed all 11 jobs in [offline CI
`31552299595`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31552299595).
Its [live-gate workflow
`31552299591`](https://github.com/yyqfrank420/ai-engineering-study-agent/actions/runs/31552299591)
skipped protected staging and model execution because the corpus is pending review. This proves the
offline tree and gate policy. It supplies no live graph or latency evidence for `fdd70d1`.

Recent branch CI had no genuine offline failure. Diagnostic `32296692133` was cancelled during
dependency installation before deployment or model execution and incurred no provider spend.
Automatic live-gate runs `31333067244` and
`31335165144` were cancelled before protected browser or model execution while their new heads were
unverified. Scheduled `main` runs `31354658015` and `31456923829` were also cancelled with no steps
or logs before manual diagnostics entered the global staging queue. These cancellations are excluded
from the product-failure ledger.

## Staged Release 1 decision

Release 1 uses a sequential request-scoped state machine:

```text
request_started
  -> component_candidate
  -> private_component_render
  -> reversible_component_preview
  -> component_gate
  -> connection_candidate
  -> private_full_render
  -> reversible_full_preview
  -> connection_gate
  -> explanation
  -> atomic_persist
```

Each stage receives the request ID, cancellation generation, immutable accepted state, and input
bounded to its layer. Steering, stop, timeout, or a failed retry ends the state machine and preserves
the preceding durable graph. No stage can publish into another request.

The staged mode applies only to applied create and edit requests. Kimi K3 high first returns a
component wire, then a connection wire. The component wire owns the root index, title, assumptions,
capabilities, and each component's label, type, responsibility, group label, group kind, and
primary-flow membership. Kimi does not author a composition layer.

The server owns IDs, group records, breadth-first sequence derivation, projection, versions,
selected maturity, exact edit admission, validation, state transitions, and persistence. A
component-only candidate has no edges. Its render gate emits a reversible preview before one Sonnet
medium component gate call. The full candidate follows the same render, reversible-preview, then
connection-gate order. Previews remain nonauthoritative until semantic acceptance and persistence.
A malformed gate result ends the request. Each layer admits two candidates;
connection retries cannot reopen an accepted component layer.
Component generation and review receive one formatted snapshot of the canonical evidence frame.
The snapshot contains the same checklist and source text for both stages, excludes canonical
evidence IDs, and marks source records as untrusted data. The selected maturity remains authoritative,
and checklist questions are review prompts rather than mandatory component rows.
The staged route does not expose `independent_risk_coverage` because it has no upstream reviewed-risk
artifact. The canonical rubric retains that rule for review paths that own such an artifact.
Connection generation and review receive the accepted component responsibilities, assumptions,
types, and capability flags. A monitoring-only path may terminate at a durable telemetry sink. A
create-time connection correction cannot add a control edge unless a locked `control` or `decision`
component owns that role. Rejected gate attempts retain bounded internal diagnostics with rule codes,
record paths, and candidate fingerprints. Prompts, reasons, and candidate content remain excluded.
For edits, the raw user message alone grants deterministic mutation authority. Contextualized
retrieval text remains available to generation and review without entering the edit-scope compiler.

Prototype gates exclude production criteria. Production proof requirements derive from the
component wire's capabilities. There is no Opus root architecture pass and no final full-model gate.
Opus low writes the explanation after both gates pass. A deterministic explanation fallback keeps an
accepted graph publishable if that call fails.

The transport atomically persists graph data and its server-only contract before authoritative
`graph_data`. `auto` edits inherit stored maturity. Legacy graphs without a stored contract default
to prototype. An explicit depth change reruns both semantic stages. A bounded edit retains exact
record authority through that restage, so maturity cannot rewrite prior records or assumptions. The
no-retry path makes five model calls and the bounded maximum is nine. The 90-second prototype
first-preview target is an SLO.
Generation calls use a 130-second timeout, gates use 55 seconds, and the request ceiling includes
orchestration and private renders.

`GRAPH_PIPELINE_MODE=legacy` is the default. A scheduled diagnostic may set `staged` for an applied
create or edit request. The larger Release 2 project DAG, project scoring, and parallel scheduling
remain deferred.

## Repeated-failure root cause

The thirty-one recent failures include architect/evidence contract, topology-wire, review/repair,
and frontend layout failures. The immediate
errors differed. The shared engineering defect was contract drift. Graph limits, model schemas,
repair permissions, review state, browser measurements, and staging measurements had separate
owners and were tested mainly through mocked boundaries. A candidate could satisfy one boundary and
remain impossible or invalid at the next one.

The convergence work makes each boundary explicit and fail-closed. The backend owns semantic graph
limits, exact repair authority, review-layer reopening, the evaluation viewport, and the post-fit
node-title floor. The browser selects a layout from actual fit and has a deterministic fallback for
the full admitted node count. The staging client consumes the candidate's criteria and has the same
node-count capacity. Private browser review receives the unchanged server candidate. Regression
tests now replay the exact latest paid candidate, exercise disconnected repair regions, preserve
locked records and passed layers, cover the 60-node layout boundary, and test the protocol failure
paths. These changes remove the known deterministic failure classes. Provider outages and new model
semantic errors can still fail closed.

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
- Existing-edge findings now carry one exact operation: update with an exact replacement label,
  remove, or replace with one or more declared addition obligations. A replacement cannot reuse an
  addition obligation claimed by another existing edge.
- Applied one omission rule to blank/null update fields; an otherwise empty update still fails.
- Enriched added node and edge presentation fields through the same defaults as initial topology generation.
- Preserved the existing graph on invalid patches and retained critic/publication validation after every repair.
- Stored the reviewed graph snapshot with the scorecard. Fingerprints and repair authority compare
  the scorecard against that exact candidate.
- Kept two successful semantic repair rounds and one separate contract-correction round. An invalid
  patch preserves the candidate and gives the next critic call a safe validation coordinate and rule.
- Added internal-test diagnostics with counters, selected depth, reopened and locked layers, finding
  codes, blocker IDs, opaque fingerprints, and correction outcomes. They omit prompts, model text,
  and graph records.

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

## Legacy graph-review convergence checkpoint

This is the historical whole-graph repair design. Once staged code lands, it has rollback-only
status. Focused offline tests cover its contracts. Diagnostic `31333075986` exercised this state on
the protected `graph-expansion` case and exposed the architect-boundary failure recorded below.
The preview-first ordering retained the same whole-graph review, repair, layer-lock, and publication
contracts. Diagnostic `31953303244` invalidated it as the Release 1 live prerequisite.

- Every initial candidate receives one exhaustive component, connection, composition, and render
  scorecard. Every deterministic finding is classified exactly once. `novice_clarity` is advisory:
  it may guide presentation improvements but cannot reject a candidate or create repair authority.
- The selected review depth is authoritative. Prototype review rejects production-only findings even
  when request text describes a production system. Architect diagram requirements are blocking critic
  context only at production depth. Production review retains all topology proofs.
- Repair patches are record-scoped and may cover non-adjacent records in the same connected
  candidate. Every cited node, edge, group, sequence, assumption, field, removal, and addition has
  its own exact permission; topology proximity grants none. Each required connection addition names
  its exact directed `source -> destination` obligation and normalized label. A mixed repair may
  include exact existing-to-existing edges beside new-component edges. Every new component still
  needs an incident edge and every connected new-component region still needs an existing graph
  anchor. A group move requires permission for both source and destination groups.
- `authored_composition` uses a server-owned title, groups, and sequence repair profile. The profile
  grants only the selected indexed or append permissions required by the failed contract; critic and
  patch output cannot widen it.
- Retained pass verdicts follow dependency invalidation. Component changes reopen components,
  connections, and composition. Edge changes reopen connections and composition. Composition-only
  changes reopen composition. Unchanged passed layers retain their prior verdict. Every candidate
  still reruns deterministic render validation.
- The workflow retains the reviewed graph snapshot beside its scorecard as the repair baseline; a
  later scorecard cannot be paired with a different graph version.
- It permits at most two successful semantic repair rounds and one error-informed critic-contract
  correction. An invalid local admission preserves the current candidate, returns its safe typed
  validation path and rule to one fresh critic correction, and consumes that correction budget. The
  corrected Kimi prompt cannot repeat the rejected prompt. After each post-patch review, the server
  derives every prior typed blocker as resolved or still failing by comparing current blocker IDs.
  The same semantic blocker may use the second repair only when the new scorecard supplies a
  different exact repair fingerprint. The same blocker with the same mutation authority fails
  closed without another Kimi call.
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
  render showed all 46 nodes and 67 edges, zero clipping or overlap, a 13.44 CSS-pixel minimum node title, and
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
  The private render had zero clipping or overlap, a 14.68 CSS-pixel minimum node title, and all eight overview
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
- Parent-reference decoding first accepted both complete zero-based and one-based parent sets. That
  compatibility path was later removed after another off-by-one failure. Forward references, cycles,
  non-integers, and out-of-range indexes still fail closed.
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

## Legacy 2026-08-14 convergence and latency state

The recent diagnostic failure ledger above is the canonical status and chronology. The entries
below retain implementation detail for the latest convergence and latency corrections.

### Legacy preview-first graph state machine

This was the legacy whole-graph repair loop before the staged Release 1 decision. It remains
available for rollback after staged code lands. Initial graph creation followed this order:

1. Kimi K3 authors one topology candidate at high effort directly from the request, selected depth,
   and server-owned topology contract. The call has one provider attempt. A deterministic schema or
   topology rejection may trigger one error-informed complete replacement within the same topology
   deadline. The correction receives the rejected candidate and sanitized validation coordinates,
   uses a distinct prompt, and has one provider attempt. A second rejection stops generation.
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

Initial topology and its first private render use a separate 170-second preview deadline. Topology
has a 140-second provider cap, private rendering retains its 15-second cap, and 15 seconds remain for
preview finalization. Post-preview review and repair retain the terminal workflow deadline. A repair
candidate uses the diagram channel's 15-second render timeout without reusing the expired
first-preview deadline. The frontend stores preview and durable graphs separately, never writes
preview view state, and promotes only an authoritative `graph_data` event.

Prototype first-preview latency has a 90-second product SLO. It does not cancel model work or change
the production deadline. Production keeps the 170-second preview allowance and the full fail-closed
review path. Semantic review remains inside the request. A detached continuation would require a
durable review job, candidate lineage, cancellation generations, and compare-and-set publication so
an old review cannot overwrite a newer turn.

Kimi does not support medium. Supported values are low, high, and max. Initial topology and repair
now use high. Diagnostic `31610799035` previously showed that high can exhaust the preview deadline,
so the next protected diagnostic must measure latency and first-pass acceptance. Opus and Sonnet
remain medium. Offline tests cannot establish provider response time.

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
- The topology wire object has no selectable index base. Parents, link endpoints, and sequence
  members are zero-based. Every root and component row carries its group label and kind, so group
  membership has no separate index or definition table. The prompt states the exact late-row parent
  bound, and safe rejection logs retain the observed and maximum index. Self-links, duplicate links,
  and links duplicating tree edges fail closed.
- `composition.steps` is one flat list of primary runtime-sequence members. The server derives each
  selected node's stage as its shortest directed distance
  from the root across selected tree edges and explicit runtime links. Invalid indexes, duplicates,
  a missing root, and unreachable selected nodes still fail closed. This removes the conflicting
  model-authored order that caused diagnostic `31612168038`.
- Passing review layers retain their prior verdict. Component changes reopen components,
  connections, and composition. Edge changes reopen connections and composition. Composition-only
  changes reopen composition. A prototype-to-production transition reopens connections and
  composition so production topology proofs cannot be inherited from a prototype review. A prior
  production proof set must also pass the canonical proof contract against its reviewed graph before
  connections may remain locked; malformed persisted rows trigger a fresh production review.
- One record-scoped patch may edit several exact disconnected regions. Every edited record remains
  named in the repair contract. Moving a node requires authority for both its source and destination
  groups. Invalid patches preserve the candidate and receive at most one error-informed contract
  correction. The workflow permits at most two successful semantic repair rounds.
- Critic component repairs declare exact existing-node field and value updates. They cannot delete a
  node. Initial prototype Architect and Sonnet reviews run concurrently after private render. Low
  and production review remain serial, and repairs do not rerun Architect.
- One initial complete-topology correction is admitted only when the remaining preview capacity is
  at least the observed first-attempt duration. A rejected correction admission preserves the
  original topology validation error and does not spend another Kimi call.
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
  Kimi K3 high for initial topology and patching, Opus 5 medium for architecture review,
  and Sonnet 5 medium for semantic review. This order is offline-tested; no live latency improvement
  is claimed.
- LLM telemetry records safe character counts and per-attempt time to first reasoning and text
  deltas. The protected eval endpoint exposes those counts without prompts or authored output so a
  future diagnostic can separate prompt ingestion, reasoning, and constrained decoding time.

## Known pre-run risks

- The 180-second visible-graph target remains live-unverified for Kimi high in the preview-first path.
  The separate preview deadline removes the serial Opus call, limits Kimi to one provider attempt,
  and reserves browser render time. The next protected case must prove that high effort completes the
  topology and that the downstream quality gates accept or safely repair it.
- Production topology proofs still allow reviewer-owned `not_applicable`. The server has no trusted
  semantic scope that states which of the five flow classes apply to a request. Deriving that scope
  from node labels, types, or the reviewer output would make model-authored text an authority. A
  later protocol may add a server-owned topology scope established before review. Current results
  are semantic attestations with structurally validated directed witnesses. Typed node roles and
  edge relations are required before the server can prove the five guarantees. This release keeps
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
