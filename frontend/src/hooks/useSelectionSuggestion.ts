import { useCallback, useEffect, useState } from 'react';

export function useSelectionSuggestion() {
  const [selectionSuggestion, setSelectionSuggestion] = useState<string | null>(null);
  const [selectionReferenceActive, setSelectionReferenceActive] = useState(false);

  useEffect(() => {
    let frameId: number | null = null;

    const syncSelection = () => {
      const active = document.activeElement;
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
        return;
      }
      const raw = window.getSelection()?.toString().replace(/\s+/g, ' ').trim() ?? '';
      if (raw.length >= 8 && raw.length <= 280) {
        setSelectionSuggestion(raw);
        setSelectionReferenceActive(false);
      } else if (!raw) {
        setSelectionSuggestion(null);
        setSelectionReferenceActive(false);
      }
    };

    const scheduleSelectionSync = () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(() => {
        frameId = null;
        syncSelection();
      });
    };

    document.addEventListener('selectionchange', scheduleSelectionSync);
    document.addEventListener('mouseup', scheduleSelectionSync);
    document.addEventListener('keyup', scheduleSelectionSync);
    document.addEventListener('touchend', scheduleSelectionSync);

    return () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
      document.removeEventListener('selectionchange', scheduleSelectionSync);
      document.removeEventListener('mouseup', scheduleSelectionSync);
      document.removeEventListener('keyup', scheduleSelectionSync);
      document.removeEventListener('touchend', scheduleSelectionSync);
    };
  }, []);

  const clearSelection = useCallback(() => {
    setSelectionSuggestion(null);
    setSelectionReferenceActive(false);
  }, []);

  const activateSelectionReference = useCallback(() => {
    setSelectionReferenceActive(true);
  }, []);

  return {
    selectionSuggestion,
    selectionReferenceActive,
    clearSelection,
    activateSelectionReference,
    dismissSelection: clearSelection,
    clearSelectionReference: clearSelection,
  };
}
