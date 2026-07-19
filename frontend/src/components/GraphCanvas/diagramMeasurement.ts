import type { DiagramLayoutReport } from '../../types';


export function measureDiagram(svg: SVGSVGElement, expectedEdges: number): DiagramLayoutReport {
  const viewport = svg.getBoundingClientRect();
  const nodes = Array.from(svg.querySelectorAll<SVGGElement>('g.node'));
  const rects = nodes.map(node => node.getBoundingClientRect());
  const edgeRects = Array.from(svg.querySelectorAll<SVGPathElement>('path.edge-vis'))
    .map(edge => edge.getBoundingClientRect());
  let overlapCount = 0;
  for (let left = 0; left < rects.length; left += 1) {
    for (let right = left + 1; right < rects.length; right += 1) {
      if (overlapArea(rects[left], rects[right]) > 12) overlapCount += 1;
    }
  }
  const clippedNodes = rects.filter(rect => isClipped(rect, viewport)).length;
  const clippedEdges = edgeRects.filter(rect => isClipped(rect, viewport)).length;
  // The node title is the essential scan target. Type/tier/entry badges are
  // deliberately secondary metadata and should not fail an otherwise readable
  // architecture merely because their decorative text is smaller.
  const fontSizes = Array.from(svg.querySelectorAll<SVGTextElement>('g.node text.node-title'))
    .map(text => {
      const declaredSize = Number.parseFloat(window.getComputedStyle(text).fontSize);
      const transform = text.getScreenCTM();
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
    clipped_edges: clippedEdges,
    minimum_text_px: fontSizes.length ? Math.min(...fontSizes) : 0,
  };
}

function isClipped(rect: DOMRect, viewport: DOMRect): boolean {
  return rect.left < viewport.left - 1
    || rect.right > viewport.right + 1
    || rect.top < viewport.top - 1
    || rect.bottom > viewport.bottom + 1;
}

function overlapArea(left: DOMRect, right: DOMRect): number {
  const width = Math.max(0, Math.min(left.right, right.right) - Math.max(left.left, right.left));
  const height = Math.max(0, Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top));
  return width * height;
}
