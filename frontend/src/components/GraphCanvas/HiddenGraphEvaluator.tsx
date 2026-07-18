import { useEffect, useRef } from 'react';
import type { DiagramLayoutReport, GraphCandidate } from '../../types';
import { agentTransport } from '../../services/agentTransport';
import { D3Graph } from './D3Graph';


interface HiddenGraphEvaluatorProps {
  candidate: GraphCandidate | null;
  viewport: { width: number; height: number };
}


export function HiddenGraphEvaluator({ candidate, viewport }: HiddenGraphEvaluatorProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const submittedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!candidate || submittedRef.current === candidate.evaluationId) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const svg = rootRef.current?.querySelector('svg');
      if (!svg || cancelled) return;
      const report = measureDiagram(svg, candidate.data.edges.length);
      try {
        const screenshot = await rasteriseSvg(svg, viewport);
        if (cancelled) return;
        submittedRef.current = candidate.evaluationId;
        agentTransport.submitDiagramEvaluation(
          candidate.evaluationId,
          candidate.graphVersion,
          report,
          screenshot,
        );
      } catch (error) {
        // A tiny valid image lets the backend receive the failure report and
        // reject the candidate deterministically instead of timing out.
        report.capture_error = error instanceof Error ? error.message : 'Browser capture failed';
        const fallback = blankScreenshot();
        submittedRef.current = candidate.evaluationId;
        agentTransport.submitDiagramEvaluation(
          candidate.evaluationId,
          candidate.graphVersion,
          report,
          fallback,
        );
      }
    }, 520);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [candidate, viewport]);

  if (!candidate) return null;
  return (
    <div
      ref={rootRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        left: '-12000px',
        top: 0,
        width: viewport.width,
        height: viewport.height,
        opacity: 0,
        pointerEvents: 'none',
        zIndex: -1,
      }}
    >
      <D3Graph
        graphData={candidate.data}
        currentStep={-1}
        activeNodeIds={new Set<string>()}
        onNodeClick={() => undefined}
      />
    </div>
  );
}


function measureDiagram(svg: SVGSVGElement, expectedEdges: number): DiagramLayoutReport {
  const viewport = svg.getBoundingClientRect();
  const nodes = Array.from(svg.querySelectorAll<SVGGElement>('g.node'));
  const rects = nodes.map(node => node.getBoundingClientRect());
  let overlapCount = 0;
  for (let left = 0; left < rects.length; left += 1) {
    for (let right = left + 1; right < rects.length; right += 1) {
      if (overlapArea(rects[left], rects[right]) > 12) overlapCount += 1;
    }
  }
  const clippedNodes = rects.filter(rect => (
    rect.left < viewport.left - 1
    || rect.right > viewport.right + 1
    || rect.top < viewport.top - 1
    || rect.bottom > viewport.bottom + 1
  )).length;
  const fontSizes = Array.from(svg.querySelectorAll<SVGTextElement>('g.node text'))
    .map(text => {
      const declaredSize = Number.parseFloat(window.getComputedStyle(text).fontSize);
      const transform = text.getScreenCTM();
      // CSS font-size alone ignores the D3 fit-to-viewport transform. Measure
      // the size a newcomer actually sees on screen after zoom/scale.
      const screenScale = transform ? Math.hypot(transform.a, transform.b) : 1;
      return declaredSize * screenScale;
    })
    .filter(value => Number.isFinite(value) && value > 0);
  return {
    viewport_width: Math.round(viewport.width),
    viewport_height: Math.round(viewport.height),
    rendered_nodes: nodes.length,
    rendered_edges: Math.min(
      expectedEdges,
      svg.querySelectorAll('path.edge-vis').length,
    ),
    overlap_count: overlapCount,
    clipped_nodes: clippedNodes,
    minimum_text_px: fontSizes.length ? Math.min(...fontSizes) : 0,
  };
}


function overlapArea(left: DOMRect, right: DOMRect): number {
  const width = Math.max(0, Math.min(left.right, right.right) - Math.max(left.left, right.left));
  const height = Math.max(0, Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top));
  return width * height;
}


async function rasteriseSvg(
  svg: SVGSVGElement,
  viewport: { width: number; height: number },
): Promise<string> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(viewport.width));
  clone.setAttribute('height', String(viewport.height));
  const xml = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas is unavailable');
    context.fillStyle = '#080d14';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.58);
  } finally {
    URL.revokeObjectURL(url);
  }
}


function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('SVG could not be rasterised'));
    image.src = url;
  });
}


function blankScreenshot(): string {
  const canvas = document.createElement('canvas');
  canvas.width = 2;
  canvas.height = 2;
  return canvas.toDataURL('image/jpeg', 0.5);
}
