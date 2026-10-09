import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { CanvasNode } from '../store';

const ACCENT: Record<string, { border: string; background: string; text: string }> = {
  end: { border: '#b91c1c', background: '#fdecec', text: '#7f1d1d' },
  gate: { border: '#7c3aed', background: '#f3edfd', text: '#4c1d95' },
  condition: { border: '#b45309', background: '#fdf3e7', text: '#78350f' },
};

/**
 * Generic node: rendered for every node type without a bespoke visual
 * (condition, gate, parallel, join, human_approval, tool, memory, delay, end).
 * Exposes source and target handles so any of them can participate in edges;
 * graph-level correctness (e.g. nothing flowing out of an end node) is
 * enforced by the graph validator at save time, not by the canvas.
 */
export default function GenericNode({ data, selected }: NodeProps<CanvasNode>) {
  const accent = ACCENT[data.nodeType] ?? { border: '#475569', background: '#f1f5f9', text: '#334155' };
  return (
    <div
      data-testid={`node-${data.nodeType}`}
      style={{
        border: `1px solid ${accent.border}`,
        background: accent.background,
        color: accent.text,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 140,
        textAlign: 'center',
        fontWeight: 600,
        outline: selected ? '2px solid #2563eb' : 'none',
        outlineOffset: 2,
      }}
    >
      <Handle type="target" position={Position.Left} />
      {data.label}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
