import NodePalette from './editor/NodePalette';
import PropertyPanel from './editor/PropertyPanel';
import WorkflowCanvas from './editor/WorkflowCanvas';

/**
 * Top-level editor shell: a persistent node palette on the left, the React
 * Flow drag-and-drop canvas filling the middle, and a right-hand property
 * inspector that configures whichever node or edge is currently selected. All
 * three read and write the shared Zustand store holding the canonical workflow
 * document.
 */
export default function App() {
  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        fontFamily: 'system-ui, sans-serif',
        margin: 0,
      }}
    >
      <NodePalette />
      <div style={{ flex: 1, position: 'relative' }}>
        <WorkflowCanvas />
      </div>
      <PropertyPanel />
    </div>
  );
}
