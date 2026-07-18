import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ThinkingIndicator } from './ThinkingIndicator';


describe('ThinkingIndicator', () => {
  it('keeps resume available after generation finishes with queued blocks', () => {
    const onTogglePause = vi.fn();

    render(
      <ThinkingIndicator
        workerStatus={{ rag: null, graph: null, critic: null, orchestrator: null, research: null }}
        workflowProgress={[{
          phase: 'explain',
          status: 'complete',
          title: 'Walkthrough complete',
          detail: 'Explanation blocks are ready.',
        }]}
        isGenerating={false}
        explanationPaused
        onTogglePause={onTogglePause}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Resume reveal' }));

    expect(onTogglePause).toHaveBeenCalledOnce();
  });
});
