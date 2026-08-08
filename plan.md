# Architecture generation recovery and staged redesign plan

Last updated: 2026-08-08

## Decision

Restore the current architecture pipeline and deploy it before starting the staged generation redesign.

The current release reached graph review on exact head `41f4881`. It produced and rendered a valid 46-node, 67-edge prototype candidate. The critic timed out because the prototype wire contract still requested five production proof rows and deadline admission reserved time for a later repair before the first verdict existed.

The redesign stays outside the release-critical path. It begins after the current pipeline passes the targeted live diagnostic and production smoke test.

## Release 1: restore the current pipeline

### Scope

1. Make topology-proof handling use the resolved architecture depth at every boundary.
2. Ignore or omit topology-proof judgments for depths that do not require them.
3. Retain strict proof validation for production depth.
4. Record safe validation paths and rule codes when critic output is rejected.
5. Add paired prototype and production tests.
6. Give the active critic verdict priority over speculative repair time while preserving synthesis and finalization.
7. Keep whole-graph generation, private render, MECE review layers, locks, and one bounded local repair.

### Current status

- Canonicalisation and final validation use the resolved architecture depth.
- Critic v37 sends an empty proof object at prototype depth and keeps the full proof contract at production depth.
- The active critic may borrow up to the existing 180-second ceiling. Patch admission assigns any remaining repair time after a failed verdict.
- Focused critic and deadline verification pass: 147 tests, including the provider-schema regression.
- The next paid action is one exact-head `graph-expansion` diagnostic. Another failure requires new evidence before any retry.

### Tests

- A prototype review with incomplete topology witnesses succeeds when all required prototype checks pass.
- The same incomplete witnesses fail at production depth.
- A corrected review can recover from one malformed response.
- Safe error telemetry identifies the rejected field and rule without storing raw prompts or model output.
- Existing graph critic, repair, workflow, API, and browser tests remain green.
- Backend and frontend coverage stay at or above their current 90% thresholds.

### Release gate

1. Run focused tests, static analysis, and the full offline CI matrix.
2. Run one targeted `graph-expansion` real-model diagnostic.
3. Require a fresh graph version, successful private render, completed semantic review, and no fallback.
4. Merge and deploy only after the exact commit passes.
5. Run a production smoke test and confirm stable traffic before beginning Release 2 work.

### Scope freeze

Release 1 must not introduce component-stage orchestration, parallel builders, a new project-state model, multi-candidate search, or new scoring layers.

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
