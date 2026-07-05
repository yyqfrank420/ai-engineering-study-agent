import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SegmentedControl } from './SegmentedControl';

describe('SegmentedControl', () => {
  it('renders options and calls onChange when selecting another option', () => {
    const onChange = vi.fn();

    render(
      <SegmentedControl
        options={[
          { value: 'auto', label: 'auto' },
          { value: 'on', label: 'on' },
          { value: 'off', label: 'off' },
        ]}
        value="auto"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByText('on'));

    expect(onChange).toHaveBeenCalledWith('on');
  });

  it('supports custom wrappers and hover styling callbacks', () => {
    const optionStyle = vi.fn((isActive: boolean, isHovered: boolean) => ({
      color: isActive ? 'red' : isHovered ? 'blue' : 'gray',
    }));

    render(
      <SegmentedControl
        options={[
          { value: 'low', label: 'low' },
          { value: 'high', label: 'high' },
        ]}
        value="low"
        onChange={vi.fn()}
        optionStyle={optionStyle}
        optionWrapper={(children, index) => (
          <span data-testid={`wrapper-${index}`}>{children}</span>
        )}
      />,
    );

    expect(screen.getByTestId('wrapper-0')).toBeTruthy();
    fireEvent.mouseEnter(screen.getByText('high'));
    expect(optionStyle).toHaveBeenCalledWith(false, true);
    fireEvent.mouseLeave(screen.getByText('high'));
    expect(optionStyle).toHaveBeenCalledWith(false, false);
  });
});
