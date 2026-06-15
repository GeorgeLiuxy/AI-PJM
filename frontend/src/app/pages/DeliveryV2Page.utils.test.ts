import { describe, expect, it } from 'vitest';

import {
  formatConfidence,
  formatDateTime,
  formatGateType,
  formatStatusLabel,
  formatTraceStage,
  hasMeaningfulMetadata,
  localizeText,
} from './DeliveryV2Page';

describe('DeliveryV2Page utility functions', () => {
  it('formats status labels used by the workbench', () => {
    expect(formatStatusLabel('')).toBe('无内容');
    expect(formatStatusLabel(null)).toBe('无内容');
    expect(formatStatusLabel('running')).toBe('运行中');
    expect(formatStatusLabel('review_blocked')).toBe('评审阻塞');
    expect(formatStatusLabel('manual_required')).toBe('需人工处理');
    expect(formatStatusLabel('custom_label')).toBe('custom_label');
    expect(formatStatusLabel(123)).toBe('123');
  });

  it('formats gate and trace labels', () => {
    expect(formatGateType(null)).toBe('未知门禁');
    expect(formatGateType('spec_ready')).toBe('规格就绪');
    expect(formatGateType('verification_passed')).toBe('验收通过');
    expect(formatTraceStage('execution_log')).toBe('执行日志');
    expect(formatTraceStage('merge_request')).toBe('合并评审');
    expect(formatTraceStage('unknown_stage')).toBe('unknown_stage');
  });

  it('formats confidence and date values without losing fallback text', () => {
    expect(formatConfidence(null)).toBeNull();
    expect(formatConfidence(0.876)).toBe('88%');
    expect(formatDateTime('invalid-date-string')).toBe('invalid-date-string');
    expect(formatDateTime('2025-06-09T13:45:00Z')).toEqual(expect.any(String));
  });

  it('detects meaningful metadata', () => {
    expect(hasMeaningfulMetadata({})).toBe(false);
    expect(hasMeaningfulMetadata({ a: '', b: null, c: undefined })).toBe(false);
    expect(hasMeaningfulMetadata({ key: 'value' })).toBe(true);
    expect(hasMeaningfulMetadata({ items: [1, 2, 3] })).toBe(true);
    expect(hasMeaningfulMetadata({ nested: { key: 'value' } })).toBe(true);
  });

  it('localizes common backend text while preserving unknown text', () => {
    expect(localizeText('Required checks passed (1/1).')).toBe('必要检查通过（1/1）。');
    expect(localizeText('Random English text')).toBe('Random English text');
    expect(localizeText('Line 1\nLine 2')).toBe('Line 1\nLine 2');
  });
});
