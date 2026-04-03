import type { GraphData } from '../types';

export interface GlossaryEntry {
  term: string;
  explanation: string;
}

type GlossaryDefinition = GlossaryEntry & {
  pattern: RegExp;
};

const GLOSSARY_DEFINITIONS: GlossaryDefinition[] = [
  {
    term: 'API',
    pattern: /\bAPI\b/i,
    explanation: 'Application programming interface: the front desk that receives requests and passes them to the right service.',
  },
  {
    term: 'LLM',
    pattern: /\bLLM\b|large language model/i,
    explanation: 'Large language model: the text-generating engine that writes or reasons over responses.',
  },
  {
    term: 'RAG',
    pattern: /\bRAG\b|retrieval-augmented generation/i,
    explanation: 'Retrieval-augmented generation: the model looks up relevant material first, then answers using that evidence.',
  },
  {
    term: 'GraphRAG',
    pattern: /\bGraphRAG\b/i,
    explanation: 'Graph-aware retrieval: answers are grounded not only in passages, but also in how concepts are linked together.',
  },
  {
    term: 'Neo4j',
    pattern: /\bNeo4j\b/i,
    explanation: 'A graph database: it stores things as nodes and relationships so connected questions are easier to answer.',
  },
  {
    term: 'Vector index',
    pattern: /\bvector index\b|\bvector store\b/i,
    explanation: 'A structure for finding semantically similar text, like matching by meaning instead of exact wording.',
  },
  {
    term: 'Embedding',
    pattern: /\bembedding(s)?\b/i,
    explanation: 'A numeric representation of text that lets the system compare meaning mathematically.',
  },
  {
    term: 'Hybrid retrieval',
    pattern: /\bhybrid retrieval\b/i,
    explanation: 'A search strategy that combines semantic search and keyword search so each covers the other’s blind spots.',
  },
  {
    term: 'Reranking',
    pattern: /\brerank(ing)?\b/i,
    explanation: 'A second-pass sorter that takes a rough shortlist and puts the most relevant evidence at the top.',
  },
  {
    term: 'Fine-tuning',
    pattern: /\bfine[- ]tuning\b/i,
    explanation: 'Training a model further on a narrow domain so it behaves more like a specialist.',
  },
  {
    term: 'LoRA',
    pattern: /\bLoRA\b/i,
    explanation: 'Low-rank adaptation: a lightweight fine-tuning method that changes a model with small add-on weights instead of rewriting everything.',
  },
  {
    term: 'PEFT',
    pattern: /\bPEFT\b/i,
    explanation: 'Parameter-efficient fine-tuning: methods that adapt a model cheaply without updating every parameter.',
  },
  {
    term: 'KV cache',
    pattern: /\bKV cache\b/i,
    explanation: 'Short-term memory for already-processed tokens so the model does not recompute the same attention work each step.',
  },
  {
    term: 'Prompt cache',
    pattern: /\bprompt cache\b/i,
    explanation: 'A cache for repeated prompt prefixes, useful when many requests share the same instructions or policy block.',
  },
  {
    term: 'Quantization',
    pattern: /\bquantization\b/i,
    explanation: 'Shrinking the model’s numeric precision to save memory and usually run faster.',
  },
  {
    term: 'INT8',
    pattern: /\bINT8\b/i,
    explanation: 'An 8-bit number format often used to run models more cheaply and with less memory.',
  },
  {
    term: 'FP16',
    pattern: /\bFP16\b/i,
    explanation: 'A 16-bit floating-point format often used to make inference faster and lighter than full precision.',
  },
  {
    term: 'TensorRT',
    pattern: /\bTensorRT\b/i,
    explanation: 'An inference optimization toolkit that helps Nvidia GPUs run models faster and more efficiently.',
  },
  {
    term: 'TTFT',
    pattern: /\bTTFT\b|time to first token/i,
    explanation: 'Time to first token: how long the user waits before the model starts replying.',
  },
  {
    term: 'TPOT',
    pattern: /\bTPOT\b|time per output token/i,
    explanation: 'Time per output token: the speed of the reply once generation has already started.',
  },
  {
    term: 'SLA',
    pattern: /\bSLA\b|service level agreement/i,
    explanation: 'A reliability or speed promise, such as how quickly a customer-service system must respond.',
  },
  {
    term: 'Continuous batching',
    pattern: /\bcontinuous batching\b/i,
    explanation: 'A serving method that keeps mixing new and ongoing requests together so the model hardware stays busy.',
  },
  {
    term: 'Throughput',
    pattern: /\bthroughput\b/i,
    explanation: 'How much total work the system can finish over time, like how many chats it can serve per second.',
  },
  {
    term: 'Latency',
    pattern: /\blatency\b/i,
    explanation: 'How long one request takes from the user’s perspective.',
  },
  {
    term: 'HNSW',
    pattern: /\bHNSW\b/i,
    explanation: 'A graph-based nearest-neighbor search method used to find similar vectors quickly.',
  },
  {
    term: 'FAISS',
    pattern: /\bFAISS\b/i,
    explanation: 'A library for fast similarity search over embeddings.',
  },
];

function collectGraphText(graphData: GraphData | null): string[] {
  if (!graphData) return [];
  return [
    graphData.title,
    ...graphData.nodes.flatMap((node) => [node.label, node.technology, node.description, node.detail ?? '']),
    ...graphData.edges.flatMap((edge) => [edge.label, edge.technology, edge.description]),
  ].filter(Boolean);
}

export function extractGlossaryEntries(
  sourceTexts: string[],
  graphData: GraphData | null,
): GlossaryEntry[] {
  const haystack = [...sourceTexts, ...collectGraphText(graphData)].join('\n');
  if (!haystack.trim()) return [];

  return GLOSSARY_DEFINITIONS
    .filter((entry) => entry.pattern.test(haystack))
    .map(({ term, explanation }) => ({ term, explanation }));
}
