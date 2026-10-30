import { useCallback } from 'react';
import type { DragEvent } from 'react';
import type { NodeType } from '../workflow/types';
import { DEFAULT_NODE_LABELS, NODE_TYPES, PALETTE_DRAG_TYPE } from './store';

/**
 * Left-hand palette listing all approved node types. Each item is HTML5
 * draggable; dropping it onto the canvas (see WorkflowCanvas) creates a node in
 * the store. The item itself does not mutate the store until it is dropped.
 */
function PaletteItem({ type }: { type: NodeType }) {
  const onDragStart = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.dataTransfer.setData(PALETTE_DRAG_TYPE, type);
      event.dataTransfer.effectAllowed = 'move';
    },
    [type],
  );

  return (
    <div
      data-testid={`palette-item-${type}`}
      draggable
      onDragStart={onDragStart}
      style={{
        border: '1px solid #cbd5e1',
        background: '#f8fafc',
        borderRadius: 6,
        padding: '8px 10px',
        cursor: 'grab',
        fontSize: 13,
        userSelect: 'none',
      }}
    >
      {DEFAULT_NODE_LABELS[type]}
    </div>
  );
}

export default function NodePalette() {
  return (
    <aside
      data-testid="node-palette"
      style={{
        width: 220,
        borderRight: '1px solid #e2e8f0',
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        overflowY: 'auto',
        background: '#ffffff',
      }}
    >
      <h2 style={{ margin: 0, fontSize: 14, color: '#334155' }}>Node Palette</h2>
      <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>
        Drag a node onto the canvas to add it.
      </p>
      {NODE_TYPES.map((type) => (
        <PaletteItem key={type} type={type} />
      ))}
    </aside>
  );
}
