import type { DiagramLayoutReport } from '../../types';


export function measureDiagram(svg: SVGSVGElement, expectedEdges: number): DiagramLayoutReport {
  const viewport = svg.getBoundingClientRect();
  const nodes = Array.from(svg.querySelectorAll<SVGGElement>('g.node'));
  const rects = nodes.map(node => node.getBoundingClientRect());
  const edgeRects = Array.from(svg.querySelectorAll<SVGPathElement>('path.edge-vis'))
    .map(edge => edge.getBoundingClientRect());
  const overviewRequiredEdgeLabels = Array.from(
    svg.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
  );
  const groupedNodes = Array.from(
    svg.querySelectorAll<SVGGElement>('g.node[data-grouped="true"]'),
  );
  const visibleGroupBoundaries = Array.from(
    svg.querySelectorAll<SVGRectElement>('g.group-box rect'),
  ).filter(boundary => isVisibleInViewport(boundary, viewport));
  const groupBoundaryRects = visibleGroupBoundaries.map(
    boundary => boundary.getBoundingClientRect(),
  );
  let overlapCount = 0;
  for (let left = 0; left < rects.length; left += 1) {
    for (let right = left + 1; right < rects.length; right += 1) {
      if (overlapArea(rects[left], rects[right]) > 12) overlapCount += 1;
    }
  }
  let groupBoundaryOverlapCount = 0;
  for (let left = 0; left < groupBoundaryRects.length; left += 1) {
    for (let right = left + 1; right < groupBoundaryRects.length; right += 1) {
      if (overlapArea(groupBoundaryRects[left], groupBoundaryRects[right]) > 12) {
        groupBoundaryOverlapCount += 1;
      }
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
    overview_required_edge_labels: overviewRequiredEdgeLabels.length,
    visible_overview_required_edge_labels: overviewRequiredEdgeLabels.filter(
      label => isVisibleInViewport(label, viewport),
    ).length,
    grouped_nodes: groupedNodes.length,
    group_labelled_nodes: groupedNodes.filter(node => {
      const label = node.querySelector<SVGTextElement>('text.node-group-label');
      return label !== null && isVisibleInViewport(label, viewport);
    }).length,
    visible_group_boundaries: visibleGroupBoundaries.length,
    group_boundary_overlap_count: groupBoundaryOverlapCount,
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

function isVisibleInViewport(element: SVGGraphicsElement, viewport: DOMRect): boolean {
  let current: Element | null = element;
  while (current && current !== element.ownerSVGElement?.parentElement) {
    const style = window.getComputedStyle(current);
    const opacity = Number.parseFloat(style.opacity);
    if (
      style.display === 'none'
      || style.visibility === 'hidden'
      || (!Number.isNaN(opacity) && opacity <= 0)
    ) {
      return false;
    }
    if (current === element.ownerSVGElement) break;
    current = current.parentElement;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && !isClipped(rect, viewport);
}
