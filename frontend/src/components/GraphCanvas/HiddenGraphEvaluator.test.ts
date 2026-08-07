import { describe, expect, it } from 'vitest';
import { measureDiagram } from './diagramMeasurement';


function rect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    toJSON: () => ({}),
  } as DOMRect;
}


describe('measureDiagram', () => {
  it('measures readable node titles without treating metadata badges as body text', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    node.classList.add('node');
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    title.classList.add('node-title');
    title.style.fontSize = '12px';
    title.getScreenCTM = () => ({ a: 0.6, b: 0 } as DOMMatrix);
    const badge = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    badge.style.fontSize = '4px';
    badge.getScreenCTM = () => ({ a: 0.6, b: 0 } as DOMMatrix);
    node.append(title, badge);
    svg.append(node, document.createElementNS('http://www.w3.org/2000/svg', 'path'));
    const edge = svg.querySelector('path');
    edge?.classList.add('edge-vis');
    svg.getBoundingClientRect = () => rect(0, 0, 720, 800);
    node.getBoundingClientRect = () => rect(100, 100, 180, 56);
    if (edge) edge.getBoundingClientRect = () => rect(280, 120, 120, 2);

    const report = measureDiagram(svg);

    expect(report.rendered_edges).toBe(1);
    expect(report.minimum_text_px).toBeCloseTo(7.2);
    expect(report.clipped_nodes).toBe(0);
    expect(report.clipped_edges).toBe(0);
  });

  it('reports an edge whose rendered geometry leaves the viewport', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const edge = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    edge.classList.add('edge-vis');
    svg.append(edge);
    svg.getBoundingClientRect = () => rect(0, 0, 720, 800);
    edge.getBoundingClientRect = () => rect(-12, 100, 80, 2);

    const report = measureDiagram(svg);

    expect(report.clipped_edges).toBe(1);
  });

  it('reports overview labels, per-node group labels, and visible boundary overlap', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.getBoundingClientRect = () => rect(0, 0, 720, 800);

    const visibleEdgeLabel = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    visibleEdgeLabel.classList.add('edge-label');
    visibleEdgeLabel.dataset.overviewRequired = 'true';
    visibleEdgeLabel.getBoundingClientRect = () => rect(200, 200, 100, 20);
    const hiddenEdgeLabel = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    hiddenEdgeLabel.classList.add('edge-label');
    hiddenEdgeLabel.dataset.overviewRequired = 'true';
    hiddenEdgeLabel.style.display = 'none';
    hiddenEdgeLabel.getBoundingClientRect = () => rect(200, 240, 100, 20);

    const labelledNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    labelledNode.classList.add('node');
    labelledNode.dataset.grouped = 'true';
    labelledNode.getBoundingClientRect = () => rect(100, 100, 180, 56);
    const groupLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    groupLabel.classList.add('node-group-label');
    groupLabel.getBoundingClientRect = () => rect(112, 106, 80, 12);
    labelledNode.append(groupLabel);
    const unlabelledNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    unlabelledNode.classList.add('node');
    unlabelledNode.dataset.grouped = 'true';
    unlabelledNode.getBoundingClientRect = () => rect(400, 100, 180, 56);

    const firstGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    firstGroup.classList.add('group-box');
    const firstBoundary = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    firstBoundary.getBoundingClientRect = () => rect(40, 40, 260, 300);
    firstGroup.append(firstBoundary);
    const secondGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    secondGroup.classList.add('group-box');
    const secondBoundary = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    secondBoundary.getBoundingClientRect = () => rect(280, 40, 260, 300);
    secondGroup.append(secondBoundary);
    const hiddenGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    hiddenGroup.classList.add('group-box');
    hiddenGroup.style.visibility = 'hidden';
    const hiddenBoundary = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    hiddenBoundary.getBoundingClientRect = () => rect(100, 100, 300, 300);
    hiddenGroup.append(hiddenBoundary);

    svg.append(
      visibleEdgeLabel,
      hiddenEdgeLabel,
      labelledNode,
      unlabelledNode,
      firstGroup,
      secondGroup,
      hiddenGroup,
    );

    const report = measureDiagram(svg);

    expect(report.overview_required_edge_labels).toBe(2);
    expect(report.visible_overview_required_edge_labels).toBe(1);
    expect(report.grouped_nodes).toBe(2);
    expect(report.group_labelled_nodes).toBe(1);
    expect(report.visible_group_boundaries).toBe(2);
    expect(report.group_boundary_overlap_count).toBe(1);
  });
});
