import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSelectionSuggestion } from '../useSelectionSuggestion';


describe('useSelectionSuggestion', () => {
  let selectedText = '';
  let pendingFrame: FrameRequestCallback | null;

  beforeEach(() => {
    selectedText = '';
    pendingFrame = null;
    vi.spyOn(window, 'getSelection').mockImplementation(() => ({
      toString: () => selectedText,
    }) as Selection);
    vi.stubGlobal('requestAnimationFrame', vi.fn(callback => {
      pendingFrame = callback;
      return 7;
    }));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function flushSelectionEvent(type = 'selectionchange') {
    act(() => {
      document.dispatchEvent(new Event(type));
      pendingFrame?.(0);
      pendingFrame = null;
    });
  }

  it('normalizes a bounded document selection and controls its reference lifecycle', () => {
    const { result } = renderHook(() => useSelectionSuggestion());
    selectedText = '  an   eight word selection for the architecture  ';

    flushSelectionEvent();

    expect(result.current.selectionSuggestion).toBe(
      'an eight word selection for the architecture',
    );
    expect(result.current.selectionReferenceActive).toBe(false);

    act(() => result.current.activateSelectionReference());
    expect(result.current.selectionReferenceActive).toBe(true);

    act(() => result.current.dismissSelection());
    expect(result.current.selectionSuggestion).toBeNull();
    expect(result.current.selectionReferenceActive).toBe(false);
  });

  it('ignores editable fields and clears empty or oversized selections', () => {
    const { result } = renderHook(() => useSelectionSuggestion());
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    selectedText = 'selected input text';

    flushSelectionEvent('mouseup');
    expect(result.current.selectionSuggestion).toBeNull();

    input.blur();
    selectedText = 'usable selected text';
    flushSelectionEvent('keyup');
    expect(result.current.selectionSuggestion).toBe('usable selected text');

    selectedText = 'x'.repeat(281);
    flushSelectionEvent('touchend');
    expect(result.current.selectionSuggestion).toBe('usable selected text');

    selectedText = '';
    flushSelectionEvent();
    expect(result.current.selectionSuggestion).toBeNull();
    input.remove();
  });

  it('coalesces pending frames and cancels one during cleanup', () => {
    const { unmount } = renderHook(() => useSelectionSuggestion());

    act(() => {
      document.dispatchEvent(new Event('selectionchange'));
      document.dispatchEvent(new Event('mouseup'));
    });
    expect(cancelAnimationFrame).toHaveBeenCalledWith(7);

    unmount();
    expect(cancelAnimationFrame).toHaveBeenCalledWith(7);
  });
});
