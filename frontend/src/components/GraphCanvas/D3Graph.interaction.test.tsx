import { fireEvent, render, screen } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { GraphData } from '../../types';
import { D3Graph } from './D3Graph';


const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Cold-chain advisory loop',
  nodes: [
    {
      id: 'sensor_gateway',
      label: 'Sensor Gateway',
      type: 'gateway',
      technology: 'Signed telemetry',
      description: 'Validates immutable temperature readings.',
      detail: null,
    },
  ],
  edges: [],
  sequence: [],
};

const originalGetBBox = SVGGraphicsElement.prototype.getBBox;
const originalWidth = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'width');
const originalHeight = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'height');

beforeAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 48, height: 12 }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'width', {
    configurable: true,
    get: () => ({ baseVal: { value: 760 } }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'height', {
    configurable: true,
    get: () => ({ baseVal: { value: 500 } }),
  });
});

afterAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true,
    value: originalGetBBox,
  });
  if (originalWidth) Object.defineProperty(SVGSVGElement.prototype, 'width', originalWidth);
  else delete (SVGSVGElement.prototype as unknown as { width?: unknown }).width;
  if (originalHeight) Object.defineProperty(SVGSVGElement.prototype, 'height', originalHeight);
  else delete (SVGSVGElement.prototype as unknown as { height?: unknown }).height;
});

describe('graph node activation', () => {
  it('exposes the node as a button and supports pointer and keyboard activation', () => {
    const onNodeClick = vi.fn();
    render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={onNodeClick}
        />
      </div>,
    );

    const node = screen.getByRole('button', { name: 'Explore Sensor Gateway' });
    fireEvent.click(node);
    fireEvent.keyDown(node, { key: 'Enter' });
    fireEvent.keyDown(node, { key: ' ' });

    expect(onNodeClick).toHaveBeenCalledTimes(3);
    expect(onNodeClick).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'sensor_gateway' }));
  });
});
