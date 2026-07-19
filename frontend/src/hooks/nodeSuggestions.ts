export function initialNodeSuggestions(label: string): string[] {
  const normalized = label.trim().replace(/\s+/g, ' ');
  const shortLabel = normalized.split(' ').slice(0, 4).join(' ') || 'this component';
  return [
    `Explain ${shortLabel} clearly`,
    `Expand graph around ${shortLabel}`,
    `Compare ${shortLabel} trade-offs`,
  ];
}
