import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { MessageList } from './MessageList';

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('MessageList', () => {
  it('does not load model-authored remote images', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'assistant-1',
            role: 'assistant',
            content: '![tracking pixel](https://tracker.example/pixel.gif)',
          },
        ]}
      />,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('[Image omitted: tracking pixel]')).toBeTruthy();
  });
});
