# Canonical Book Graph v1

Last updated: 2026-05-09

## Summary

Build a canonical, evidence-backed graph at ingestion time from the existing `AI Engineering` book chunks, then switch runtime graph generation from “LLM invents nodes/edges” to “retrieve chunks -> select canonical subgraph -> render/explain.”

This v1 covers the whole book, uses no manual curation of extracted graph instances, keeps the current `nodes/edges/sequence/groups` UI contract, supports concept + architecture through two linked ontology layers, and abstains cleanly when support is too weak.

The offline pipeline is:

`parent_docs.pkl -> extract -> normalize -> verify -> merge -> edge validation -> confidence scoring -> artifact write`

## Goals

- Replace free-form runtime graph invention with a stable canonical graph derived offline.
- Preserve the current frontend graph contract so the runtime swap is low-risk.
- Prioritize precision, stability, and evidence coverage over recall and graph size.
- Keep FAISS retrieval as the runtime retrieval source of truth in v1.
- Avoid Neo4j or other graph databases in v1; file-based graph artifacts are the canonical store.

## Non-Goals

- No manual editing of extracted nodes or edges in v1.
- No fallback to the current free-form graph generator when canonical graph support is weak.
- No multi-book support in this phase.
- No graph database dependency in this phase.

## Source of Truth

- Corpus: `AI Engineering` by Chip Huyen only.
- Retrieval: existing FAISS artifacts remain the runtime retrieval source of truth.
- Chunk source: `data/faiss/parent_docs.pkl`
- UI contract: existing frontend `GraphData` payload shape

## Offline Graph Build Pipeline

### Overview

Add a new build step that reads `data/faiss/parent_docs.pkl` and writes canonical graph artifacts under `data/graph/`.

Assign stable IDs before extraction:

- `parent_chunk_id = ai-eng:p{page_number}:pc{parent_chunk_index}`
- `child_chunk_id = {parent_chunk_id}:cc{child_chunk_index}`

Use this exact pipeline:

1. extract candidates
2. normalize to ontology
3. verify against source text
4. merge canonical entities
5. edge validation
6. confidence scoring
7. artifact write

### 1. Extract candidates

For each parent chunk, run a strict JSON extractor that emits:

- concept candidates
- architecture-node candidates
- relation candidates

Each candidate must include:

- raw label(s)
- proposed kind
- quoted support span or exact source sentence(s)
- `parent_chunk_id`

### 2. Normalize to ontology

Map raw candidates into canonical kinds and relation vocabulary.

Reject candidates that cannot be mapped unambiguously.

Normalization rules:

- map labels and kinds into the fixed ontology only
- reject relation near-synonyms unless the registry explicitly maps them
- keep concept and architecture layers separate
- never normalize across layers

### 3. Verify against source text

Use a hybrid verifier:

- deterministic checks first
- constrained LLM verifier second only for plausible candidates

Deterministic checks:

- source span exists in chunk text
- labels are anchored in the chunk
- relation is legal for the normalized kind pair
- source and target are distinct canonical IDs

LLM verifier output:

- `supported` | `unsupported` | `ambiguous`
- short rationale
- exact supporting quote indices or copied support string

Drop all `unsupported` and `ambiguous` candidates in v1.

### 4. Merge canonical entities

Merge verified candidates by canonical label and alias rules within the same layer.

Rules:

- merge aliases within a layer only
- never merge across layers
- exact and near-exact label normalization is allowed
- case-folding, punctuation stripping, and simple singular/plural normalization are allowed
- acronym-to-expanded-form pairing is allowed only when deterministic or explicitly captured by the schema

### 5. Edge validation

Recheck all verified edges against the final canonical source and target kinds.

Reject anything outside the allowed matrix.

### 6. Confidence scoring

Score nodes and edges from:

- evidence count
- verification result
- cross-chunk repetition
- normalization certainty

Use confidence primarily for display gating, not for broad ranking logic.

### 7. Artifact write

Write final JSON artifacts plus a build report.

## Ontology and Relation Registry

Use two linked layers, not one mixed ontology.

### Concept layer

Node kinds:

- `method`
- `component`
- `control`
- `decision`
- `metric`
- `risk`
- `artifact`
- `objective`

### Architecture layer

Node kinds:

- `actor`
- `service`
- `datastore`
- `pipeline_stage`
- `control`
- `external`

### Cross-layer links

Keep cross-layer links, but define them narrowly and explicitly:

- `implements`
- `supports`
- `applies_to`

These three relations must never be used within a single layer in v1.

### Relation registry

Every relation must be defined in a machine-readable registry, for example:

`data/graph_schema/relations.json`

Each relation entry must include:

- `relation`
- `definition`
- `allowed_source_kinds`
- `allowed_target_kinds`
- `positive_examples`
- `negative_examples`

The extractor, normalizer, and verifier must all consume the same registry.

Negative examples are required and treated as first-class constraints.

### Initial relation set

Concept relations:

- `part_of`
- `depends_on`
- `feeds_into`
- `compares_with`
- `constrains`
- `improves`
- `risks`
- `evaluates`

Architecture relations:

- `calls`
- `routes_to`
- `reads_from`
- `writes_to`
- `stores_in`
- `uses`
- `monitors`
- `sends_to`

Cross-layer relations:

- `implements`
- `supports`
- `applies_to`

### Strict relation semantics

Treat near-synonyms as invalid unless the registry explicitly maps them.

In particular:

- `depends_on` means target is a prerequisite or required input for source to function correctly.
- `uses` means source consumes or invokes target without asserting prerequisite semantics.
- `feeds_into` means output of source becomes input to target.
- `implements` is cross-layer only: an architecture node realizes a concept or method.
- `supports` is cross-layer only: an architecture or concept node enables but does not realize the target directly.
- `applies_to` is cross-layer only: a concept, control, or decision governs or is relevant to a specific architecture node or stage.

## Artifact Shapes

Emit:

- `concepts.json`
- `architecture_nodes.json`
- `edges.json`
- `chunk_links.json`
- `build_report.json`
- `relations.json` or equivalent schema registry if not already stored elsewhere

### Node artifact fields

- `canonical_id`
- `layer`
- `label`
- `aliases`
- `kind`
- `description`
- `chapter_refs`
- `source_chunk_ids`
- `confidence`

### Edge artifact fields

- `edge_id`
- `layer` or `cross_layer`
- `source_id`
- `target_id`
- `relation`
- `supporting_chunk_ids`
- `support_spans`
- `confidence`

### Chunk-link artifact fields

- `parent_chunk_id`
- `canonical_node_ids`
- `canonical_edge_ids`

## Runtime Graph Selection

Keep FAISS retrieval unchanged for v1.

Replace free-form graph generation with:

1. retrieve top parent chunks
2. map retrieved `parent_chunk_id`s to canonical entities and edges
3. choose graph layer
4. score seed nodes from retrieval rank plus chunk frequency
5. expand one hop within the chosen layer
6. include cross-layer edges only when both endpoint nodes are already selected and the query explicitly warrants it
7. emit a bounded graph
8. abstain if too little high-confidence structure survives gating

### Layer selection

- if the query explicitly asks for system architecture, request flow, service layout, deployment, or component interactions, use `architecture`
- otherwise use `concept`

### Graph bounds

- concept graph: `4-7` nodes
- architecture graph: `5-10` nodes

### Abstain rule

Abstain if fewer than `3` high-confidence nodes or fewer than `2` evidence-backed edges survive gating.

### Runtime LLM usage

Runtime LLM use is limited to:

- title generation
- `sequence` generation from already-selected canonical nodes
- short explanation text

Runtime LLM must not invent new graph nodes or edges.

## UI and Compatibility

Preserve the existing frontend graph contract:

- `graph_type`
- `title`
- `nodes`
- `edges`
- `sequence`
- `groups?`

Add only optional metadata:

- node: `layer?`, `canonical_id?`, `confidence?`, `evidence_chunk_ids?`
- edge: `relation?`, `confidence?`, `supporting_chunk_ids?`

Keep current rendering behavior if optional fields are absent.

Node detail should prefer canonical evidence and source chunks first. Explanatory prose may still use the current enrichment path, but graph structure must come only from canonical artifacts.

## Test Plan

### Offline build tests

- stable `parent_chunk_id` generation from the same `parent_docs.pkl`
- schema validation for all graph artifact JSON files
- relation-registry validation:
  - every relation has definition, allowed kinds, positive examples, negative examples
  - every emitted edge uses a registered relation
- negative-example enforcement:
  - candidates matching a relation’s negative examples are rejected in normalization or verification
- verification tests:
  - missing support span -> reject
  - illegal kind pair -> reject
  - ambiguous verifier result -> reject
- merge tests:
  - aliases collapse within a layer
  - no accidental merge across layers
- confidence tests:
  - more independent support increases confidence
  - unverifiable candidates never receive displayable confidence

### Runtime tests

- retrieved chunk IDs map to canonical nodes and edges correctly
- layer selection defaults to `concept` unless the query is clearly architectural
- graph output stays within node and edge bounds
- low-confidence queries abstain without falling back to the old generator
- existing frontend graph payload remains valid

### Canary evaluation without gold labels

Add a fixed `canary_prompts.json` with `30-50` prompts and paraphrase groups.

Track:

- `schema_violation_rate`
- `edge_evidence_coverage`
- `node_evidence_coverage`
- same-prompt rerun stability
- paraphrase stability
- duplicate canonical label rate
- abstain rate
- verifier rejection rate

Gate thresholds:

- `schema_violation_rate = 0`
- `edge_evidence_coverage = 100%`
- `node_evidence_coverage >= 95%`
- same-prompt rerun node-ID Jaccard `>= 0.90`
- paraphrase-group node-ID Jaccard `>= 0.60`
- duplicate canonical label rate within a layer `< 5%`
- canary abstain rate `<= 30%`

## Assumptions and Defaults

- Source corpus is only `AI Engineering` by Chip Huyen.
- Existing chunks and FAISS artifacts remain the retrieval source of truth.
- No manual editing of extracted nodes or edges is allowed in v1.
- Hand-authoring the ontology schema and relation registry is allowed and required.
- Neo4j is out of scope for v1; file-based artifacts are the canonical graph store.
- Cross-layer relations are narrowly scoped and only used when explicitly justified by query intent.
- Precision and stability take priority over recall and graph size.
