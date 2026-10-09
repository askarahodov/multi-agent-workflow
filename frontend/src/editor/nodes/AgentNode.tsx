import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { CanvasNode } from '../store';

/**
 * Agent node: represents an agent execution step. It can be configured via the
 * property panels (downstream task T3); here it is a styled card with both
 * source and target handles so it can sit in the middle of a workflow.
 */
export default function AgentNode({ data, selected }: NodeProps<CanvasNode>) {
  return (
    <div
      data-testid={`node-${data.nodeType}`}
      style={{
        border: '1px solid #1d4ed8',
        background: '#e8effc',
        color: '#1e3a8a',
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 140,
        textAlign: 'center',
        fontWeight: 600,
        outline: selected ? '2px solid #2563eb' : 'none',
        outlineOffset: 2,
      }}
    >
      {data.label}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
