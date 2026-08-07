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

  it('renders the supported study markdown, math, and explanation metadata', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'user-rich',
            role: 'user',
            content: [
              '# Architecture',
              '## Retrieval',
              '### Ranking',
              '**Strong** and *grounded* with $x + y$.',
              '- semantic search',
              '1. retrieve',
              '> Preserve evidence.',
              '| Layer | Tool |\n| --- | --- |\n| API | FastAPI |',
              '---',
              '[Book](https://example.com/book)',
              '$$z = x + y$$',
            ].join('\n\n'),
          },
          {
            id: 'assistant-explanation',
            role: 'assistant',
            kind: 'explanation',
            title: 'Why retrieval matters',
            content: 'Evidence reaches the answer.',
            relatedNodeIds: ['retrieval_api', 'vector_store', 'ranker', 'answer', 'ignored'],
            isStreaming: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole('heading', { level: 1, name: 'Architecture' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Retrieval' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 3, name: 'Ranking' })).toBeTruthy();
    expect(screen.getByText('Strong').tagName).toBe('STRONG');
    expect(screen.getByText('grounded').tagName).toBe('EM');
    expect(container.querySelector('blockquote')).not.toBeNull();
    expect(container.querySelector('table')).not.toBeNull();
    expect(container.querySelector('hr')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'Book' })).toHaveProperty('target', '_blank');
    expect(container.querySelectorAll('.katex')).not.toHaveLength(0);
    expect(screen.getByText('Why retrieval matters')).toBeTruthy();
    expect(screen.getByText('retrieval api')).toBeTruthy();
    expect(screen.getByText('answer')).toBeTruthy();
    expect(screen.queryByText('ignored')).toBeNull();
    expect(screen.getAllByTestId(/message-/)).toHaveLength(2);
  });

  it('renders a stable empty state', () => {
    render(<MessageList messages={[]} />);

    expect(screen.getByText('Ask a question about AI Engineering…')).toBeTruthy();
  });
});
