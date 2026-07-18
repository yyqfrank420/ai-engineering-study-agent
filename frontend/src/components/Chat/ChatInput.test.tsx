import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatInput } from './ChatInput';

const defaultProps = {
  onSend: vi.fn(),
  onStop: vi.fn(),
  onPrepare: vi.fn(),
  threadId: 'thread-1' as string | null,
  disabled: false,
  sendDisabled: false,
  showPrepare: false,
  prepareDisabled: false,
  prepareMessage: null as string | null,
  isGenerating: false,
  complexity: 'auto' as const,
  graphMode: 'auto' as const,
  researchEnabled: false,
  onComplexityChange: vi.fn(),
  onGraphModeChange: vi.fn(),
  onResearchChange: vi.fn(),
  selectionSuggestion: null as string | null,
  selectionReferenceActive: false,
};

function renderInput(threadId: string | null, overrides = {}) {
  return render(
    <ChatInput
      {...defaultProps}
      {...overrides}
      threadId={threadId}
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
        {...defaultProps}
        threadId="thread-1"
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
        {...defaultProps}
        threadId="thread-2"
      />,
    );

    expect((screen.getByPlaceholderText('Ask a question…') as HTMLTextAreaElement).value).toBe('');
  });

  it('sends trimmed content on Enter and clears the draft', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: '  explain agents  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledWith('explain agents');
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('sends via the button and reports draft changes', () => {
    const onSend = vi.fn();
    const onDraftChange = vi.fn();
    renderInput('thread-1', { onSend, onDraftChange });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: '  explain evals  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect(onDraftChange).toHaveBeenCalledWith(true);
    expect(onDraftChange).toHaveBeenLastCalledWith(false);
    expect(onSend).toHaveBeenCalledWith('explain evals');
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('does not send empty disabled or backend-blocked drafts', () => {
    const onSend = vi.fn();
    const { rerender } = renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: 'blocked' } });
    rerender(<ChatInput {...defaultProps} threadId="thread-1" disabled onSend={onSend} />);
    fireEvent.keyDown(screen.getByPlaceholderText('Ask a question…'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();

    rerender(<ChatInput {...defaultProps} threadId="thread-1" sendDisabled onSend={onSend} />);
    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'blocked' } });
    fireEvent.keyDown(screen.getByPlaceholderText('Ask a question…'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('keeps newline behavior for Shift+Enter', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'line one' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('shows stop button while generating', () => {
    const onStop = vi.fn();
    renderInput('thread-1', { isGenerating: true, onStop });

    const button = screen.getByRole('button', { name: 'Stop generation' });
    fireEvent.mouseEnter(button);
    expect(button.style.background).toBe('rgba(248, 81, 73, 0.2)');
    fireEvent.mouseLeave(button);
    expect(button.style.background).toBe('rgba(248, 81, 73, 0.1)');
    fireEvent.click(button);

    expect(onStop).toHaveBeenCalled();
  });

  it('keeps the composer active and submits steering while generating', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { isGenerating: true, onSend });
    const input = screen.getByPlaceholderText('Steer the active response…');

    fireEvent.change(input, { target: { value: 'focus on the approval boundary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Steer response' }));

    expect(onSend).toHaveBeenCalledWith('focus on the approval boundary');
    expect((input as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByRole('button', { name: 'Stop generation' })).toBeTruthy();
  });

  it('applies hover focus blur handlers and closes the popover on outside click', () => {
    renderInput('thread-1', {
      complexity: 'production',
      graphMode: 'on',
      researchEnabled: true,
    });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.focus(input);
    expect((input as HTMLTextAreaElement).style.borderColor).toBe('rgba(167, 139, 250, 0.5)');
    fireEvent.blur(input);
    expect((input as HTMLTextAreaElement).style.borderColor).toBe('rgba(255, 255, 255, 0.08)');

    fireEvent.click(screen.getByRole('button', { name: 'Message options' }));
    expect(screen.getByText('COMPLEXITY')).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText('COMPLEXITY')).toBeNull();
  });

  it('shows prepare button and notice while backend is warming', () => {
    const onPrepare = vi.fn();
    renderInput('thread-1', {
      showPrepare: true,
      prepareMessage: 'Backend is warming up',
      onPrepare,
    });

    expect(screen.getByText('Backend is warming up')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Prepare backend' }));

    expect(onPrepare).toHaveBeenCalled();
  });

  it('shows unavailable prepare label and honors disabled prepare state', () => {
    const onPrepare = vi.fn();
    renderInput('thread-1', {
      showPrepare: true,
      prepareDisabled: true,
      prepareMessage: 'Backend unavailable',
      onPrepare,
    });

    const button = screen.getByRole('button', { name: 'Prepare backend' });
    expect(button.textContent).toBe('Prepare');
    fireEvent.click(button);
    expect(onPrepare).not.toHaveBeenCalled();
  });

  it('opens mode popover and updates complexity graph mode and research toggle', () => {
    const onComplexityChange = vi.fn();
    const onGraphModeChange = vi.fn();
    const onResearchChange = vi.fn();
    renderInput('thread-1', {
      onComplexityChange,
      onGraphModeChange,
      onResearchChange,
    });

    fireEvent.click(screen.getByRole('button', { name: 'Message options' }));
    fireEvent.click(screen.getByText('prod'));
    fireEvent.click(screen.getByText('on'));
    fireEvent.click(screen.getByText('Augment with Web Search').parentElement!.nextSibling as Element);

    expect(onComplexityChange).toHaveBeenCalledWith('production');
    expect(onGraphModeChange).toHaveBeenCalledWith('on');
    expect(onResearchChange).toHaveBeenCalledWith(true);
  });

  it('handles highlighted text suggestion lifecycle', () => {
    const onUseSelection = vi.fn();
    const onDismissSelection = vi.fn();
    const onClearSelectionReference = vi.fn();
    renderInput('thread-1', {
      selectionSuggestion: 'Selected paragraph',
      selectionReferenceActive: true,
      onUseSelection,
      onDismissSelection,
      onClearSelectionReference,
    });

    expect(screen.getByPlaceholderText('Ask a question about the highlighted text…')).toBeTruthy();
    fireEvent.click(screen.getByText('Referenced'));
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss highlighted text' }));
    fireEvent.focus(screen.getByPlaceholderText('Ask a question about the highlighted text…'));

    expect(onUseSelection).toHaveBeenCalled();
    expect(onDismissSelection).toHaveBeenCalled();
    expect(onClearSelectionReference).toHaveBeenCalled();
  });

  it('activates highlighted text when typing before reference is active', () => {
    const onUseSelection = vi.fn();
    renderInput('thread-1', {
      selectionSuggestion: 'Selected paragraph',
      selectionReferenceActive: false,
      onUseSelection,
    });

    fireEvent.change(screen.getByPlaceholderText('Ask a question about the highlighted text…'), {
      target: { value: 'compare this' },
    });

    expect(onUseSelection).toHaveBeenCalled();
  });
});
