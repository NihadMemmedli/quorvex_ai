import { describe, expect, it } from 'vitest';

import { getNextSteps, getNodeById, getNodeForPath, pipelineEdges, pipelineNodes } from './workflow';

describe('workflow navigation utilities', () => {
  it('maps dashboard paths to pipeline nodes', () => {
    expect(getNodeForPath('/exploration')).toBe('exploration');
    expect(getNodeForPath('/specs/spec-1')).toBe('specs');
    expect(getNodeForPath('/runs/run-1')).toBe('runs');
    expect(getNodeForPath('/settings')).toBeNull();
  });

  it('keeps pipeline edges aligned with known nodes', () => {
    const nodeIds = new Set(pipelineNodes.map((node) => node.id));

    for (const edge of pipelineEdges) {
      expect(nodeIds.has(edge.from)).toBe(true);
      expect(nodeIds.has(edge.to)).toBe(true);
    }

    expect(getNodeById('analytics')?.href).toBe('/analytics');
  });

  it('returns contextual next steps for major workflow stages', () => {
    expect(getNextSteps('/requirements').map((step) => step.href)).toEqual(['/rtm', '/specs/new']);
    expect(getNextSteps('/runs').map((step) => step.href)).toEqual(['/analytics', '/schedules']);
    expect(getNextSteps('/unknown')).toEqual([]);
  });
});
