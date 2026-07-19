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
    svg.querySelector('path')?.classList.add('edge-vis');
    svg.getBoundingClientRect = () => rect(0, 0, 720, 800);
    node.getBoundingClientRect = () => rect(100, 100, 180, 56);

    const report = measureDiagram(svg, 1);

    expect(report.rendered_edges).toBe(1);
    expect(report.minimum_text_px).toBeCloseTo(7.2);
    expect(report.clipped_nodes).toBe(0);
  });
});
