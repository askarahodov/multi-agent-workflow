import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { CanvasNode } from '../store';

/**
 * Start node: the single entry point of a workflow. It only exposes a source
 * handle (workflow starts here, nothing flows into it).
 */
export default function StartNode({ data, selected }: NodeProps<CanvasNode>) {
  return (
    <div
      data-testid={`node-${data.nodeType}`}
      style={{
        border: '1px solid #1f7a5c',
        background: '#e6f4ec',
        color: '#0d3324',
        borderRadius: 999,
        padding: '8px 16px',
        minWidth: 120,
        textAlign: 'center',
        fontWeight: 600,
        outline: selected ? '2px solid #2563eb' : 'none',
        outlineOffset: 2,
      }}
    >
      {data.label}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
