import { useEffect, useRef } from 'react';
import type { GraphCandidate } from '../../types';
import { agentTransport } from '../../services/agentTransport';
import { D3Graph } from './D3Graph';
import { measureDiagram } from './diagramMeasurement';


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
        await submitWithRetry(
          candidate.evaluationId,
          candidate.graphVersion,
          report,
          screenshot,
          () => cancelled,
        );
      } catch (error) {
        // A tiny valid image lets the backend receive the failure report and
        // reject the candidate deterministically instead of timing out.
        report.capture_error = error instanceof Error ? error.message : 'Browser capture failed';
        const fallback = blankScreenshot();
        await submitWithRetry(
          candidate.evaluationId,
          candidate.graphVersion,
          report,
          fallback,
          () => cancelled,
        );
      }
      if (!cancelled) submittedRef.current = candidate.evaluationId;
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
      inert
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


async function submitWithRetry(
  evaluationId: string,
  graphVersion: string | null | undefined,
  report: ReturnType<typeof measureDiagram>,
  screenshot: string,
  isCancelled: () => boolean,
): Promise<void> {
  const delays = [0, 250, 750, 1_500];
  for (const delay of delays) {
    if (delay > 0) await new Promise(resolve => window.setTimeout(resolve, delay));
    if (isCancelled()) return;
    if (agentTransport.submitDiagramEvaluation(evaluationId, graphVersion, report, screenshot)) {
      return;
    }
  }
  throw new Error('Diagram evaluation transport was unavailable');
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
