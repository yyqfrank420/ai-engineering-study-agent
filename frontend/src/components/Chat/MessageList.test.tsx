import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { MessageList } from './MessageList';

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('MessageList', () => {
  it('keeps inline code inline and renders fenced code in one valid pre block', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'assistant-code',
            role: 'assistant',
            content: 'Route through `response_generator`.\n\n```ts\nconst safe = true;\n```',
          },
        ]}
      />,
    );

    const inlineCode = screen.getByText('response_generator');
    expect(inlineCode.tagName).toBe('CODE');
    expect(inlineCode.closest('p')).not.toBeNull();
    expect(inlineCode.closest('pre')).toBeNull();
    expect(container.querySelectorAll('pre')).toHaveLength(1);
    expect(container.querySelector('pre pre')).toBeNull();
    expect(container.querySelector('pre code.language-ts')).not.toBeNull();
  });

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
