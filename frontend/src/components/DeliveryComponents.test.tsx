import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBadge } from '../app/pages/DeliveryV2Page';

describe('StatusBadge', () => {
  it('renders empty values as Chinese empty text', () => {
    render(<StatusBadge value={null} />);

    expect(screen.getByText('无内容')).toBeInTheDocument();
  });

  it('uses success, warning, running, and critical tones from real component logic', () => {
    const cases = [
      { value: 'completed', label: '已完成', className: 'bg-emerald-50' },
      { value: 'failed', label: '失败', className: 'bg-amber-50' },
      { value: 'running', label: '运行中', className: 'bg-blue-50' },
      { value: 'critical', label: '严重', className: 'bg-rose-50' },
    ];

    cases.forEach(({ value, label, className }) => {
      const { container, unmount } = render(<StatusBadge value={value} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(container.querySelector(`.${className}`)).toBeInTheDocument();
      unmount();
    });
  });

  it('preserves unknown labels and truncates long text', () => {
    const { container } = render(<StatusBadge value="very_long_status_name_that_should_be_truncated" />);

    expect(screen.getByText('very_long_status_name_that_should_be_truncated')).toBeInTheDocument();
    expect(container.querySelector('.truncate')).toBeInTheDocument();
  });
});
