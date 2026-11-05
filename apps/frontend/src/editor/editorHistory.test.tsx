import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it } from 'vitest';
import { useEditorStore } from './store';
import NodePalette from './NodePalette';

beforeEach(() => { cleanup(); act(() => useEditorStore.getState().reset()); });
afterEach(() => cleanup());

describe('document-scoped undo/redo and accessible palette', () => {
  it('records node, edge, metadata and configuration edits in bounded history', () => {
    const get = () => useEditorStore.getState();
    act(() => {
      get().addNode('start',{x:0,y:0});
      get().addNode('agent',{x:200,y:0});
      const nodes = get().definition.nodes;
      get().addEdge(nodes[0].id,nodes[1].id);
      get().updateNodeLabel(nodes[1].id,'Ревьюер');
    });
    expect(get().definition.nodes[1].label).toBe('Ревьюер');
    expect(get().definition.edges).toHaveLength(1);
    act(() => get().undo());
    expect(get().definition.nodes[1].label).toBe('Agent');
    act(() => get().undo());
    expect(get().definition.edges).toHaveLength(0);
    act(() => get().redo());
    expect(get().definition.edges).toHaveLength(1);
    act(() => get().updateMetadata({name:'Заново'}));
    expect(get().future).toHaveLength(0);
    expect(get().past.length).toBeGreaterThan(0);
    act(() => {
      for(let i=0;i<100;i++) get().updateMetadata({name:'title-'+i});
    });
    expect(get().past.length).toBeLessThanOrEqual(60);
  });

  it('keeps selection and document history separate; resets on import/open', () => {
    const get = () => useEditorStore.getState();
    act(() => get().addNode('agent',{x:0,y:0}));
    const snapshot = get().definition;
    act(() => get().selectNode(snapshot.nodes[0].id));
    expect(get().past).toHaveLength(1);
    act(() => get().load(snapshot));
    expect(get().past).toHaveLength(0);
    expect(get().future).toHaveLength(0);
    act(() => get().undo());
    expect(get().definition).toEqual(snapshot);
    act(() => get().addNode('end',{x:200,y:0}));
    act(() => get().reset());
    expect(get().definition.nodes).toHaveLength(0);
    expect(get().past).toHaveLength(0);
  });

  it('lets keyboard users add any node without dragging and select it', () => {
    render(<NodePalette />);
    fireEvent.click(screen.getByTestId('palette-add-start'));
    fireEvent.click(screen.getByTestId('palette-add-agent'));
    const nodes=useEditorStore.getState().definition.nodes;
    expect(nodes.map(n=>n.type)).toEqual(['start','agent']);
    expect(nodes[0].position.x).toBe(0);
    expect(nodes[1].position.x).toBe(220);
    expect(useEditorStore.getState().selectedNodeId).toBe(nodes[1].id);
    act(()=>useEditorStore.getState().undo());
    expect(useEditorStore.getState().definition.nodes).toHaveLength(1);
  });
});
