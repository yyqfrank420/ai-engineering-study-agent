import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatInput } from './ChatInput';

function renderInput(threadId: string | null) {
  return render(
    <ChatInput
      onSend={vi.fn()}
      onStop={vi.fn()}
      onPrepare={vi.fn()}
      threadId={threadId}
      disabled={false}
      sendDisabled={false}
      showPrepare={false}
      prepareDisabled={false}
      prepareMessage={null}
      isGenerating={false}
      complexity="auto"
      graphMode="auto"
      researchEnabled={false}
      onComplexityChange={vi.fn()}
      onGraphModeChange={vi.fn()}
      onResearchChange={vi.fn()}
      selectionSuggestion={null}
      selectionReferenceActive={false}
    />,
  );
}

describe('ChatInput', () => {
  it('preserves the draft when bootstrapping from no thread to the first active thread', () => {
    const view = renderInput(null);
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'why is send disabled?' } });

    view.rerender(
      <ChatInput
        onSend={vi.fn()}
        onStop={vi.fn()}
        onPrepare={vi.fn()}
        threadId="thread-1"
        disabled={false}
        sendDisabled={false}
        showPrepare={false}
        prepareDisabled={false}
        prepareMessage={null}
        isGenerating={false}
        complexity="auto"
        graphMode="auto"
        researchEnabled={false}
        onComplexityChange={vi.fn()}
        onGraphModeChange={vi.fn()}
        onResearchChange={vi.fn()}
        selectionSuggestion={null}
        selectionReferenceActive={false}
      />,
    );

    expect((screen.getByPlaceholderText('Ask a question…') as HTMLTextAreaElement).value).toBe('why is send disabled?');
  });

  it('clears the draft when switching between real threads', () => {
    const view = renderInput('thread-1');
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'carry this over' } });

    view.rerender(
      <ChatInput
        onSend={vi.fn()}
        onStop={vi.fn()}
        onPrepare={vi.fn()}
        threadId="thread-2"
        disabled={false}
        sendDisabled={false}
        showPrepare={false}
        prepareDisabled={false}
        prepareMessage={null}
        isGenerating={false}
        complexity="auto"
        graphMode="auto"
        researchEnabled={false}
        onComplexityChange={vi.fn()}
        onGraphModeChange={vi.fn()}
        onResearchChange={vi.fn()}
        selectionSuggestion={null}
        selectionReferenceActive={false}
      />,
    );

    expect((screen.getByPlaceholderText('Ask a question…') as HTMLTextAreaElement).value).toBe('');
  });
});
