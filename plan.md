# Architecture generation recovery and staged redesign plan

Last updated: 2026-08-10

## Decision

Restore the current architecture pipeline and deploy it before starting the staged generation redesign.

The current release completes architecture planning, Kimi generation, private rendering, at most two semantic repairs, one error-informed critic-contract correction, and post-patch review. The reviewed graph snapshot stays beside its scorecard. Dependency-aware layer retention reopens downstream review when an upstream owned record changes. A request-scoped four-call ceiling bounds Sonnet critic provider calls across all review stages. Diagnostic `31257810429` exposed serial semantic defect discovery. Diagnostic `31259489721` exposed serial scorecard validation. Diagnostic `31261404727` exposed model-owned completion state, which critic v41 replaced with a server-owned merge. Diagnostic `31262285743` then exposed a direct schema/parser contradiction: the provider schema allowed categorical strings while the applied topology parser required integer codes. The parser now accepts only the finite canonical codebook names or their integer codes.

The redesign stays outside the release-critical path. It begins after the current pipeline passes the targeted live diagnostic with fresh explicit authorization and then passes the production smoke test.

## Release 1: restore the current pipeline

### Scope

1. Make topology-proof handling use the resolved architecture depth at every boundary.
2. Ignore or omit topology-proof judgments for depths that do not require them.
3. Retain strict proof validation for production depth.
4. Record safe validation paths and rule codes when critic output is rejected.
5. Add paired prototype and production tests.
6. Give the active critic verdict priority over speculative repair time while preserving synthesis and finalization.
7. Keep whole-graph generation, private render, MECE review layers, dependency-aware retention and reopening, at most two semantic repairs, and one error-informed critic-contract correction. Treat `novice_clarity` as advisory, and fail closed when a repeated still-failing obligation would consume an identical repair class.
8. Complete the first exhaustive editable review before spending the repair budget.

### Current status

- Canonicalisation and final validation use the resolved architecture depth.
- Prototype review sends an empty proof object and production review keeps the full proof contract.
- The initial review returns one exhaustive scorecard. One bounded protocol correction can repair a malformed scorecard. A rejected patch can receive one separate error-informed contract correction with a safe validation path and rule.
- The shared initial critic stage may borrow up to 195 seconds. The measured timing replay preserves 98 seconds for patching and 101 seconds for final review.
- Repair scope is derived from failed layer ownership. It grants exact permissions for cited non-adjacent records in one connected candidate and exact directed connection obligations. `authored_composition` uses a server-owned title, groups, and sequence repair profile. Every added component region must connect to an existing node. Group moves require both source and destination group authority. Editable defects enter at most two successful bounded repair rounds and one contract correction; a repeated still-failing prior obligation cannot consume an identical repair class. Render-only defects fail closed.
- Diagnostic `31333075986` exposed a local architect response-limit conflict and an invalid fallback path before the intended graph review could complete. The current recovery removes that conflict and fails closed when architecture input is unavailable.
- Diagnostic `31335429802` failed at `architecture_pass_evidence_provenance` before graph construction. It made two application calls, no judge calls, and cost $0.353252. The architect took 139.767 seconds and emitted 9,931 output tokens; synthesis took 25.602 seconds. The turn took 168.228 seconds and the case took 170.265 seconds. No graph, private render, fallback, Kimi, Sonnet, repair, or second turn ran.
- Diagnostic `31340006983` reached the corrected evidence contract but the Opus architect exhausted its 150-second role deadline at `xhigh` effort. The accepted provider attempt ran for 149.813 seconds with zero final output and no queue wait. The turn failed closed before Kimi, Sonnet, rendering, repair, or turn two. Architect effort is now `high`; the model, response contract, independent review, and deadline stay unchanged.
- Diagnostic `31369358742` ran only `graph-expansion` on merged head `77df25e7`. The Opus architect completed at `high` effort in 111.877 seconds, then provenance validation rejected `evidence_basis[2].evidence_ref` with the private rule `unknown_evidence_id`. The turn took 153.688 seconds and cost $0.300365. No graph, private render, Kimi, Sonnet, repair, or second turn ran. The pending corpus made the workflow report-only; it was not an AI-eval pass.
- Canonical book and web evidence IDs remain hashed server-owned records. The architect and challenger receive short request-scoped slots such as `source_1`. The server accepts only those slots at each model boundary and resolves them to canonical IDs before validation and storage. Later graph and synthesis prompts retain evidence claims but omit canonical coordinates. Unknown slots, source-type mismatches, display citations, URLs, and model-supplied canonical IDs fail closed with generic public coordinates.
- The graph-expansion corpus explicitly requests monitoring in the first prompt and limits the second prompt to one directly connected child.
- Corpus `2026-08-09.v1` is pending a fresh full protected capture, human review, judge calibration, and approved manifest hash. No live success is recorded. No further paid run is authorized.
- The current offline matrix passes 1,224 backend tests and 217 frontend tests.

### Tests

- A prototype review with incomplete topology witnesses succeeds when all required prototype checks pass.
- The same incomplete witnesses fail at production depth.
- A corrected review can recover from one malformed response.
- An initial editable rejection receives exactly one completion pass before repair.
- A completion may add defects and selectors. Omitted prior repair evidence remains in the server-owned merged contract. The reviewed graph snapshot and scorecard remain paired by graph version.
- Post-patch reviews do not start another completion pass.
- `novice_clarity` produces advice only. Post-patch reviews classify every prior server obligation as resolved or still failing, and repeated still-failing obligations fail closed before a second repair in the same server-tracked class.
- Safe error telemetry identifies the rejected field and rule without storing raw prompts or model output.
- Existing graph critic, repair, workflow, API, and browser tests remain green.
- Backend and frontend coverage stay at or above their current 90% thresholds.

### Release gate

1. The focused tests, static analysis, and full offline CI matrix have passed on the current tree.
2. After fresh explicit authorization, run one targeted `graph-expansion` real-model diagnostic.
3. Require a fresh graph version, successful private render, completed semantic review, and explicit `approved`, `preserved`, or `withheld` publication state. An edit cannot fall back to creation.
4. Merge and deploy only after the exact commit passes.
5. Run a production smoke test and confirm stable traffic before beginning Release 2 work.

### Scope freeze

Release 1 must not introduce component-stage orchestration, parallel builders, a new project-state model, multi-candidate search, generated layers, or new scoring layers. The staged DAG and layer-as-generated architecture remain Release 2 work.

## Release 2: staged architecture generation

### Goal

Generate one accepted architecture through project-wide risk gates. Each worker changes a scoped part of an immutable project snapshot. Every gate evaluates the complete current project, its maturity stage, remaining plan, and proposed patch.

### Authoritative state

Use a versioned contract-and-evidence DAG. The component hierarchy is one projection of this state.

The state owns:

- User requirements and explicit constraints.
- Prioritised quality-attribute scenarios.
- Architecture decisions and considered alternatives.
- Components and ownership boundaries.
- Interface assumptions and guarantees.
- Runtime, data, deployment, trust, and delivery views.
- Open risks, counterexamples, and verification evidence.
- Artifact fingerprints, dependencies, and acceptance status.

Conversation history is audit information. Gate decisions are recomputed from the canonical state.

### Two orchestration loops

The outer project loop owns decomposition, priorities, integration, and replanning. The inner work loop generates or repairs one scoped proposal.

```text
Root requirements and scenarios
            |
      root design gate
            |
   dependency-ready queue
      /      |       \
 frontend  backend   data
      \      |       /
    parent integration gate
            |
      next ready queue
            |
      final clean audit
```

### Gate input

- Project version and complete accepted snapshot.
- Proposed patch with declared read set, write set, and base version.
- Current stage and remaining work plan.
- Requirements, quality scenarios, decisions, contracts, and risks.
- Deterministic validation results and private render evidence.

### Gate output

- Disposition: `accept`, `repair`, or `replan`.
- Conformance: properties proved by the current snapshot.
- Maturity: requirements expected at the current stage.
- Readiness: feasibility of closing remaining requirements and risks.
- Project score before and after the patch.
- Verified counterexamples.
- Exact repair scope.
- Reopened and invalidated artifacts.
- Next work priority.

Each counterexample contains an invariant, witness path, failure, affected records, and repair scope. One malformed finding invalidates that finding rather than the whole review.

### Component contracts

Each component declares:

- Responsibilities and authoritative state it owns.
- Provided interfaces and guarantees.
- Required interfaces and environmental assumptions.
- Identity, ordering, consistency, retry, timeout, and failure semantics.
- Quality scenarios it helps satisfy.
- Deterministic evidence available to the gate.

Independent branches may run concurrently after their shared contracts pass. Parent integration gates prove that component assumptions are supplied by peers or the environment.

### Scoring and work selection

The live gate uses project-level difference rewards:

```text
patch_value = score(project + patch) - score(project)
```

Hard invariant failures and regressions in accepted contracts reject the patch before soft scoring.

Pairwise interaction value is evaluated only for patches that share interfaces. Tree-aware Shapley or Owen-style attribution runs offline for model and prompt analysis.

The scheduler selects work by expected risk reduction, requirements unblocked, critical-path relief, model cost, and expected stale-work cost. Attribution does not choose the next task.

### Parallel execution

- Use a bounded dependency-ready queue.
- Generate independent proposals concurrently against immutable snapshots.
- Run deterministic checks, specialist reviews, and private renders concurrently.
- Serialize the short acceptance transaction with compare-and-set on the project version.
- Reapply and reevaluate stale proposals against the latest snapshot.
- Pause the failed component, its descendants, and affected contract peers.
- Allow unrelated branches to continue.
- Limit speculative work to one unaccepted component per independent branch initially.

### Invalidation and locks

- Every accepted artifact is content-addressed from its declared inputs.
- Every gate records the dependencies it read.
- A changed contract invalidates its reverse dependency closure.
- An internal repair that preserves the observable contract retains dependent approvals.
- An equal rebuilt fingerprint restores prior approvals through change pruning.
- A final clean evaluation must agree with the incremental result before publication.

### Avoiding local maxima

Keep two or three alternatives only at expensive, high-risk decisions such as persistence ownership, synchronous versus event-driven control flow, AI orchestration ownership, and regional recovery strategy.

Eliminate alternatives as scenario evidence resolves the tradeoff. Reopen an accepted parent decision only when a verified counterexample identifies the violated invariant and affected paths.

Stop decomposition when responsibilities are independently verifiable, interfaces form natural boundaries, and implementation ownership remains contained. Do not use node or edge counts as quality limits.

### Views and rendering

The semantic project model is authoritative. Generate coordinated views for system context, components, runtime flow, data flow, deployment, trust boundaries, and release controls.

The root view provides the readable overview. Component views preserve the detail required for implementation. Visual repair owns layout fields and cannot change semantic contracts.

## Delivery phases for Release 2

### Phase A: typed project and gate contracts

- Add the canonical project snapshot, quality scenarios, contracts, risks, evidence, and gate result types.
- Replace monolithic critic failure with independently validated counterexamples.
- Preserve the current builder behind the existing public interface.

Exit criterion: the current whole graph can pass through the new gate contract without behaviour changes.

### Phase B: dependency and invalidation engine

- Add declared read and write sets, artifact fingerprints, compare-and-set acceptance, and reverse dependency invalidation.
- Add clean-versus-incremental equivalence tests.

Exit criterion: deterministic tests prove exact invalidation, stale proposal handling, and change pruning.

### Phase C: staged generation

- Generate and review the root plan and quality scenarios.
- Generate components as scoped patches.
- Add parent integration gates and local repair.
- Keep the existing one-shot external user experience.

Exit criterion: staged generation matches or exceeds the current corpus pass rate without increasing semantic regressions.

### Phase D: bounded parallelism

- Add the dependency-ready scheduler and one-ahead speculation.
- Measure time to first visible plan, time to accepted architecture, cost, stale work, and repair locality.

Exit criterion: lower median completion latency with bounded cost and no increase in integration failures.

### Phase E: alternatives and adaptive routing

- Add root alternatives at recorded sensitivity points.
- Route models and review depth using matched corpus evidence.
- Keep hidden eval cases and blind model identity in comparative review.

Exit criterion: measured improvement on held-out architecture cases and stable protocol-valid rates.

## Rollout

- Keep the current pipeline as the production default during Release 2 development.
- Run the staged pipeline in shadow mode on the rotating corpus.
- Store exact prompt, model, scorer, snapshot, latency, cost, and outcome versions.
- Compare both pipelines on matched cases.
- Enable staged generation for internal traffic after it meets the release thresholds.
- Roll back through one configuration switch.
- Remove the old path only after staged generation passes the agreed production observation window.

## Main risks

- Integration synthesis can erase parallel latency gains.
- A learned judge can reward verbosity or ornamental complexity.
- Early root decisions can trap later work in a local maximum.
- Hidden dependencies can make incremental approvals unsound.
- Repeated full-state prompts can dominate cost and latency.

Controls include explicit contracts, deterministic checks, independent rubric owners, bounded concurrency, cached canonical state, verified counterexamples, root alternatives, and one final clean audit.

## Research basis

- [SEI Attribute-Driven Design](https://www.sei.cmu.edu/library/attribute-driven-design-method-collection/)
- [LLM-assisted Attribute-Driven Design](https://arxiv.org/abs/2506.22688)
- [Learning assumptions for compositional verification](https://ntrs.nasa.gov/citations/20030017771)
- [Program Synthesis by Sketching](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-176.html)
- [Bazel Skyframe](https://bazel.build/reference/skyframe)
- [Rewarding Progress](https://arxiv.org/abs/2410.08146)
- [Magentic-One](https://arxiv.org/abs/2411.04468)
- [CodePlan](https://arxiv.org/abs/2309.12499)
- [OptiLoop](https://arxiv.org/abs/2605.27630)
- [Silo-Bench](https://arxiv.org/abs/2603.01045)
- [LLM-based Automated Architecture View Generation](https://arxiv.org/abs/2603.21178)
- [When to Stop Decomposing](https://doi.org/10.1109/ACCESS.2026.3683195)
