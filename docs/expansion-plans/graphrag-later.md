# GraphRAG Later

This document captures the future plan for a lightweight GraphRAG layer.

We are **not** building this now.

## Why This Came Up

The current app is:

- FAISS-only dense retrieval over child chunks
- parent-section expansion
- LLM-generated graph from retrieved text
- async node-detail enrichment from the same retrieval layer

This works, but it has two limits:

1. Retrieval quality is only okay because it relies on one dense search path.
2. Graph quality is only okay because the graph worker is generating nodes and edges from whatever chunks happened to be retrieved, instead of grounding them in a stable concept structure from the book.

## Important Distinction

We do **not** want full Microsoft-style GraphRAG right now.

That would mean:

- a heavier indexing pipeline
- persistent graph extraction at larger scale
- community detection
- global map-reduce style search
- much more implementation and operational complexity

What we *might* want later is a **light graph-aware RAG** layer:

- better retrieval for content quality
- lightweight concept graph artifacts for grounding quality

## What To Build Later

### Phase 1: Better Retrieval

Before any graph-aware work, improve the basic retrieval stack:

- BM25 lexical retrieval over parent sections
- FAISS + BM25 fusion
- larger candidate recall before trimming
- later: reranking, multi-query expansion, HyDE

This should improve content quality even without any GraphRAG artifacts.

### Phase 2: Concept Artifacts At Index Time

During content-update / index-build time, generate:

- `concepts.json`
- `concept_edges.json`
- `chunk_concepts.json`
- optional `chapter_summaries.json`

Suggested shapes:

`concepts.json`
- `concept_id`
- `label`
- `aliases`
- `description`
- `chunk_ids`

`concept_edges.json`
- `source`
- `target`
- `relation`
- `supporting_chunk_ids`
- optional `weight`

`chunk_concepts.json`
- `chunk_id`
- `concept_ids`

### Phase 3: Graph-Aware Retrieval

At query time, retrieval should return more than chunks:

- top chunks
- matched concepts
- 1-hop neighboring concepts
- supporting relations
- optional chapter summary context

The retrieval bundle should then feed:

- the synthesizer
- the graph worker
- node-click enrichment

### Phase 4: Ground The Graph Worker

The graph worker should stop inventing most nodes and edges from raw chunks alone.

Instead it should:

- start from retrieved concepts
- use neighboring concepts as expansion candidates
- use the LLM mainly for selection, organization, explanation, and presentation

### Phase 5: Graph-Aware Node Enrichment

When a node is clicked, enrichment should use:

- the concept itself
- aliases
- supporting chunks
- connected concept edges
- nearby concepts

That should make node detail feel grounded instead of generic.

## What This Is Expected To Improve

If done well, the light GraphRAG layer should improve:

- consistency of graph nodes across similar questions
- edge quality
- node-click follow-up grounding
- concept coverage for broad study questions

It should **not** be treated as a replacement for stronger retrieval basics.

## Retrieval Evaluation Problem

We do **not** get honest IR precision/recall unless we have labeled relevance judgments.

So if this is built later, evaluate it with a layered approach:

### 1. Small Curated Gold Set

Create a hand-labeled benchmark of around `30-60` study questions.

For each item, store:

- `question`
- `must_have_chunk_ids`
- optional `good_chunk_ids`
- `must_have_concepts`

This is where real metrics like:

- `Recall@k`
- `MRR`
- `nDCG`

can be computed honestly.

### 2. Synthetic Retrieval Dataset

Generate retrieval cases from the book itself:

- sample chunks/sections
- ask an LLM to produce answerable questions
- keep the source chunk ids and concept ids as weak supervision

Use this for regression coverage, not as final truth.

### 3. Judge-Based Sufficiency

For each query, ask a judge model whether the retrieved bundle is:

- sufficient
- noisy
- missing key concepts

These are proxy metrics, not true precision/recall.

### 4. Graph-Specific Metrics

Add graph-aware checks such as:

- concept hit rate
- edge support rate
- node enrichment grounding rate
- graph stability across similar questions

## Honest Naming For Metrics

Do not label judge-based or synthetic metrics as plain precision/recall.

Use names like:

- `gold_recall_at_k`
- `concept_coverage`
- `context_sufficiency`
- `noise_rate`
- `node_grounding_rate`

## Recommended Future Build Order

If this work is resumed later, the safest order is:

1. hybrid retrieval
2. concept artifacts
3. graph-aware retrieval bundle
4. grounded graph worker
5. graph-aware node enrichment
6. retrieval + graph evals

## Non-Goals For The Future Version

Still avoid these unless the project grows much larger:

- full Microsoft GraphRAG stack
- community detection
- graph database dependency
- multi-document ontology design
- heavy global search infrastructure

## Summary

Later, if we want better graph quality and better retrieval quality together, the right move is:

- stronger hybrid retrieval for content quality
- lightweight concept graph artifacts for grounding quality

That is the practical version of GraphRAG for this app.
