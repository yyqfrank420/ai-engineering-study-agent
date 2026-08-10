import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { GraphEdge, GraphNode } from '../../types';
import { GlossaryDrawer } from './GlossaryDrawer';
import { NodeDetailPopup } from './NodeDetailPopup';
import { SequenceBar } from './SequenceBar';


const serviceNode: GraphNode = {
  id: 'service',
  label: 'Retrieval API',
  type: 'service',
  technology: 'FastAPI',
  description: 'Retrieves grounded evidence.',
  detail: 'The book recommends measuring retrieval quality.',
  book_refs: ['Chapter 6', 'Chapter 8'],
  tier: 'public',
};

const edges: GraphEdge[] = [
  {
    source: 'service',
    target: 'store',
    label: 'queries vector index',
    technology: 'HTTPS',
    sync: 'async',
    description: 'Carries a search request.',
  },
  {
    source: 'client',
    target: 'service',
    label: 'submits question',
    technology: 'JSON',
    sync: 'sync',
    description: 'Carries user input.',
  },
];


describe('graph detail controls', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders node evidence and connection metadata and invokes its actions', () => {
    const onClose = vi.fn();
    const onTellMeMore = vi.fn();
    const onExpandGraph = vi.fn();
    render(
      <NodeDetailPopup
        node={serviceNode}
        edges={edges}
        onClose={onClose}
        onTellMeMore={onTellMeMore}
        onExpandGraph={onExpandGraph}
      />,
    );

    expect(screen.getByText('SERVICE')).toBeTruthy();
    expect(screen.getByText('PUBLIC')).toBeTruthy();
    expect(screen.getByText('Chapter 6')).toBeTruthy();
    expect(screen.getByText('queries vector index')).toBeTruthy();
    expect(screen.getByText('submits question')).toBeTruthy();
    expect(screen.getByText('ASYNC')).toBeTruthy();

    fireEvent.click(screen.getByText('Tell me more'));
    fireEvent.click(screen.getByText('Expand graph'));
    const close = screen.getByLabelText('Close node detail');
    fireEvent.mouseEnter(close);
    fireEvent.mouseLeave(close);
    fireEvent.click(close);

    expect(onTellMeMore).toHaveBeenCalledWith(serviceNode);
    expect(onExpandGraph).toHaveBeenCalledWith(serviceNode);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not claim network accessibility for applied architecture nodes', () => {
    render(
      <NodeDetailPopup
        node={{ ...serviceNode, design_origin: 'applied' }}
        edges={[]}
        onClose={vi.fn()}
        onTellMeMore={vi.fn()}
        onExpandGraph={vi.fn()}
      />,
    );

    expect(screen.queryByText('PUBLIC')).toBeNull();
    expect(screen.queryByText('PRIVATE')).toBeNull();
  });

  it('keeps decision nodes bounded to explanation', () => {
    render(
      <NodeDetailPopup
        node={{
          ...serviceNode,
          id: 'gate',
          label: 'Approval Gate',
          type: 'decision',
          technology: '',
          description: '',
          detail: null,
          book_refs: [],
          tier: 'private',
        }}
        edges={[]}
        onClose={vi.fn()}
        onTellMeMore={vi.fn()}
        onExpandGraph={vi.fn()}
      />,
    );

    expect(screen.getByText('PRIVATE')).toBeTruthy();
    expect(screen.queryByText('Expand graph')).toBeNull();
    expect(screen.getByText('Ask the chat to explain this constraint more clearly.')).toBeTruthy();
    expect(screen.queryByText('CONNECTIONS')).toBeNull();
  });

  it('opens, resizes, drags, and closes a glossary derived from response text', () => {
    vi.useFakeTimers();
    const { container } = render(
      <GlossaryDrawer
        graphData={null}
        sourceTexts={['RAG calls an API and searches a vector index.']}
        bottomOffset="1rem"
      />,
    );

    const trigger = screen.getByText('Dictionary');
    fireEvent.click(trigger);
    expect(screen.getByText('RAG')).toBeTruthy();
    expect(screen.getByText('API')).toBeTruthy();
    expect(screen.getByText('Vector index')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Open larger glossary'));
    expect(screen.getByLabelText('Use compact glossary')).toBeTruthy();
    const header = screen.getByText('Acronyms & terms').parentElement?.parentElement as HTMLElement;
    fireEvent.pointerDown(header, { clientX: 10, clientY: 20 });
    fireEvent.pointerMove(window, { clientX: 30, clientY: 50 });
    expect((container.firstChild as HTMLElement).style.transform).toBe('translate(20px, 30px)');
    fireEvent.pointerUp(window);

    fireEvent.click(trigger);
    expect(screen.getByText('Acronyms & terms')).toBeTruthy();
    act(() => vi.runOnlyPendingTimers());
    fireEvent.click(screen.getByLabelText('Close glossary'));
    expect(screen.queryByText('Acronyms & terms')).toBeNull();
  });

  it('does not render an empty glossary', () => {
    const { container } = render(
      <GlossaryDrawer graphData={null} sourceTexts={[]} bottomOffset="1rem" />,
    );
    expect(container.firstChild).toBeNull();
  });
});


describe('SequenceBar', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('supports overview navigation, scrubbing, hover feedback, and dismissal', () => {
    const onStepChange = vi.fn();
    const onDismiss = vi.fn();
    const view = render(
      <SequenceBar
        currentStep={-1}
        totalSteps={3}
        stepDescription=""
        onStepChange={onStepChange}
        onDismiss={onDismiss}
      />,
    );

    const previous = screen.getByLabelText('Previous step');
    fireEvent.mouseEnter(previous);
    fireEvent.mouseLeave(previous);
    fireEvent.click(screen.getByLabelText('Next step'));
    fireEvent.click(screen.getByLabelText('Go to step 2'));
    expect(onStepChange).toHaveBeenNthCalledWith(1, 0);
    expect(onStepChange).toHaveBeenNthCalledWith(2, 1);

    view.rerender(
      <SequenceBar
        currentStep={1}
        totalSteps={3}
        stepDescription="Validate evidence"
        onStepChange={onStepChange}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.mouseEnter(screen.getByLabelText('Previous step'));
    fireEvent.mouseLeave(screen.getByLabelText('Previous step'));
    fireEvent.click(screen.getByLabelText('Previous step'));
    expect(onStepChange).toHaveBeenLastCalledWith(0);
    expect(screen.getByText('Validate evidence')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Exit walkthrough'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('autoplays, pauses, completes, and restarts a walkthrough', () => {
    vi.useFakeTimers();
    const onStepChange = vi.fn();
    const view = render(
      <SequenceBar
        currentStep={-1}
        totalSteps={2}
        stepDescription=""
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText('Play'));
    expect(onStepChange).toHaveBeenCalledWith(0);
    expect(screen.getByLabelText('Pause')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Pause'));

    fireEvent.click(screen.getByLabelText('Play'));
    view.rerender(
      <SequenceBar
        currentStep={1}
        totalSteps={2}
        stepDescription="Done"
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );
    act(() => vi.advanceTimersByTime(1800));
    expect(onStepChange).toHaveBeenCalledWith(-1);

    fireEvent.click(screen.getByLabelText('Play'));
    expect(onStepChange).toHaveBeenLastCalledWith(0);
  });

  it('uses a counter for long walkthroughs and bounds last-step navigation', () => {
    const onStepChange = vi.fn();
    render(
      <SequenceBar
        currentStep={12}
        totalSteps={13}
        stepDescription="Final review"
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText('Step 13 of 13')).toBeTruthy();
    expect(screen.getByLabelText('Next step')).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByLabelText('Next step'));
    expect(onStepChange).not.toHaveBeenCalled();
  });
});
