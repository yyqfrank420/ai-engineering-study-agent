import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SplitPane } from './SplitPane';

function stubViewport(stacked: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: stacked,
    media: '(max-width: 1023px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

describe('SplitPane responsive and accessible resizing', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('supports keyboard resizing for the desktop separator', () => {
    stubViewport(false);
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);

    const separator = screen.getByRole('separator', { name: 'Resize graph and conversation panes' });
    expect(separator.getAttribute('aria-orientation')).toBe('vertical');
    expect(separator.getAttribute('aria-valuenow')).toBe('60');
    fireEvent.keyDown(separator, { key: 'ArrowLeft' });
    expect(separator.getAttribute('aria-valuenow')).toBe('55');
    fireEvent.keyDown(separator, { key: 'Home' });
    expect(separator.getAttribute('aria-valuenow')).toBe('40');
    fireEvent.keyDown(separator, { key: 'End' });
    expect(separator.getAttribute('aria-valuenow')).toBe('80');
  });

  it('stacks graph above chat and uses vertical arrow keys on narrow screens', () => {
    stubViewport(true);
    const { container } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);

    expect(container.querySelector('.split-pane')?.classList.contains('split-pane--stacked')).toBe(true);
    const separator = screen.getByRole('separator');
    expect(separator.getAttribute('aria-orientation')).toBe('horizontal');
    fireEvent.keyDown(separator, { key: 'ArrowDown' });
    expect(separator.getAttribute('aria-valuenow')).toBe('65');
  });

  it('removes a hidden graph separator from the tab order', () => {
    stubViewport(false);
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} graphVisible={false} />);
    expect(screen.getByRole('separator', { hidden: true }).getAttribute('tabindex')).toBe('-1');
  });
});
