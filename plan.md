# Architecture generation recovery and staged redesign plan

Last updated: 2026-08-16

## Decision

Replace the legacy whole-graph repair loop with a small staged pipeline behind a feature flag. The
staged pipeline is the next recovery path. It does not require the deferred Release 2 project DAG,
project scoring, or parallel scheduling.

The legacy release used architecture planning, Kimi generation, private rendering, up to two semantic repairs, one error-informed critic-contract correction, and post-patch review. The reviewed graph snapshot stayed beside its scorecard. Dependency-aware layer retention reopened downstream review when an upstream owned record changed. A request-scoped four-call ceiling bounded Sonnet critic provider calls across all review stages. Diagnostic `31257810429` exposed serial semantic defect discovery. Diagnostic `31259489721` exposed serial scorecard validation. Diagnostic `31261404727` exposed model-owned completion state, which critic v41 replaced with a server-owned merge. Diagnostic `31262285743` then exposed a direct schema/parser contradiction: the provider schema allowed categorical strings while the applied topology parser required integer codes. The parser accepted only the finite canonical codebook names or their integer codes.

Diagnostic `31953303244` invalidated the Release 1 live prerequisite for the legacy pipeline. It
made 13 application calls, cost $1.166855, and took 752.114 seconds. Turn 1 published a 14-node,
19-edge graph. Turn 2 created a 15-node candidate, then its final connections contract failed
`invalid_contract`; the workflow restored the 14-node graph. A path that can add the requested
component and then discard it at the final contract gate is not a valid release prerequisite.

The legacy path remains available only as a feature-flag rollback once staged code lands. It must
not receive another release-validation attempt as the preferred production design.

## Release 1: staged pipeline recovery

### Scope

1. Build one request-scoped state machine with explicit server-owned stages.
2. Generate the root and each graph layer as typed partial input. The server alone materializes,
   validates, versions, and persists canonical graph data.
3. Permit one bounded retry per layer, shared by generation and review. A failed retry fails the
   request and preserves the preceding durable graph.
4. Apply maturity rules at each stage. A later stage may consume only server-accepted records from
   its prerequisite stages.
5. Emit reversible component previews after a mature component stage and a reversible full preview
   after the final renderable graph stage.
6. Persist after deterministic maturity and render checks. There is no final whole-graph model gate.
7. Select the staged pipeline only for applied create and edit requests when the diagnostic flag
   requests it. The legacy pipeline remains the default and rollback path.

### Chosen state machine

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

Every stage is request-scoped. It receives the request ID, cancellation generation, immutable
accepted state from earlier stages, and bounded input for its own layer. Steering or cancellation
ends the current state machine and starts a new one. No stage can publish into a later request.

Kimi K3 at high effort first returns a component wire, then a connection wire. The component wire
owns the root index, title, assumptions, capabilities, and each component's label, type,
responsibility, group label, group kind, and primary-flow membership. Kimi does not author a
composition layer.

The server owns IDs, group records, breadth-first sequence derivation, graph projection, versions,
selected maturity, exact edit admission, state transitions, validation, and persistence. It derives
production proofs from declared capabilities. Prototype gates exclude production criteria. Models
never write canonical graph data or decide state transitions.

A component-only graph has no edges. Its deterministic render gate emits a reversible preview before
one Sonnet medium component gate call. The full graph follows the same render, reversible-preview,
then connection-gate order. Each preview remains nonauthoritative until its semantic gate passes and
the final turn persists. Each gate handles one candidate. A malformed
gate result is terminal. Each layer admits at most two candidates. A rejected component candidate
can retry that layer; a rejected connection candidate can retry connections without reopening an
accepted component layer.

There is no Opus root architecture pass and no final full-model gate. Opus low writes the
explanation after both layer gates pass. A deterministic explanation is used when that call fails.
The transport atomically persists graph data and its server-only graph contract before emitting
authoritative `graph_data`.

For edits, `auto` inherits stored maturity. A legacy graph without a contract defaults to prototype.
An explicit different depth reruns both semantic stages at the selected maturity. A bounded edit keeps
its exact record authority during that restage, so maturity never grants permission to rewrite prior
components, edges, title, groups, sequence, or assumptions. Prompt wording cannot alter selected
maturity.

The no-retry path makes five application model calls: component generation, component gate,
connection generation, connection gate, and explanation. The bounded maximum is nine calls. The
prototype 90-second first-preview target is an SLO. Generation calls use a 130-second timeout,
gates use 55 seconds, and the request ceiling includes orchestration and private renders.

### Current status

- Diagnostic `31953303244` is failure 25 in the live ledger and invalidates the former Release 1
  prerequisite.
- The staged pipeline is the release work. The legacy repair loop is retained for rollback-only
  after staged code lands.
- The existing full offline matrix remains a prerequisite for any staged diagnostic.

### Tests

- Each stage accepts only server-accepted data from its predecessor.
- Each layer permits a second candidate and rejects a third.
- Model output cannot create, mutate, version, or persist a canonical graph directly.
- The component preview contains no edges and passes private rendering before the component gate.
- The full graph passes private rendering before the connection gate.
- Cancellation, steering, timeout, retry failure, and persistence failure restore the prior durable graph.
- The feature flag selects one pipeline for a request and prevents mixed legacy and staged writes.
- Existing graph, transport, API, browser, static-analysis, and coverage gates remain green.

### Release gate

1. The focused tests, static analysis, and full offline CI matrix have passed on the current tree.
2. Run the staged `graph-expansion` diagnostic with `pipeline_mode=staged`.
3. Require it to persist a fresh 15-node turn 2 graph rather
   than restoring turn 1.
4. Record latency, cost, preview, retry, maturity, and rollback telemetry.
5. Merge and deploy only after the exact commit passes.

### Scope freeze

Release 1 includes only the request-scoped sequential state machine, server-owned layer contracts,
one retry per layer, maturity checks, progressive previews, and a feature flag. It excludes a
project-wide DAG, scoring, parallel builders, speculative work, alternatives, and adaptive routing.

## Release 2: deferred project DAG, scoring, and parallelism

### Goal

Release 2 remains deferred until the staged Release 1 path has production evidence. It may add a
project-wide risk-gated DAG, project scoring, and bounded parallel work. It must preserve the
server-owned graph contract and maturity rules established in Release 1.

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

- Keep the legacy pipeline as the default behind `GRAPH_PIPELINE_MODE=legacy`.
- Permit `GRAPH_PIPELINE_MODE=staged` only for the scheduled diagnostic applied create/edit path.
- Record stage latency, retries, maturity failures, preview outcomes, graph versions, cost, and
  rollback use.
- Disabling staged diagnostics routes new requests to the legacy pipeline. Once staged code lands,
  the legacy repair loop has rollback-only status.
- Remove the legacy path after the agreed production observation window.

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
