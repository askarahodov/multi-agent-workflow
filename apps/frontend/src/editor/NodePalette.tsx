import { useCallback } from 'react';
import type { DragEvent } from 'react';
import type { NodeType } from '../workflow/types';
import { NODE_TYPES, PALETTE_DRAG_TYPE, useEditorStore } from './store';
import { NODE_HELP, DRAFT_TEMPLATES, buildDraftTemplate, type TemplateId } from './nodeGuides';

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
      <strong>{NODE_HELP[type].title}</strong>
      <p style={{margin:'4px 0 0',fontSize:11,color:'#475569'}}>{NODE_HELP[type].purpose}</p>
    </div>
  );
}

export default function NodePalette() {
  const load = useEditorStore(s=>s.load);
  const current = useEditorStore(s=>s.definition);
  const onTemplate = (id: TemplateId) => {
    if ((current.nodes.length > 0 || current.edges.length > 0) &&
        !window.confirm('Заменить текущий черновик? Несохранённые изменения будут потеряны.')) return;
    load(buildDraftTemplate(id));
  };
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
      <h2 style={{ margin: 0, fontSize: 14, color: '#334155' }}>Ноды процесса</h2>
      <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>Перетащите ноду на схему. Нажмите на неё, чтобы узнать назначение и настройки. Пока это черновой редактор: исполняемый граф ещё не реализован.</p>
      <h3 style={{margin:'10px 0 0',fontSize:13}}>Готовые черновики</h3>
      {DRAFT_TEMPLATES.map(template=><button key={template.id} type="button" data-testid={`draft-template-${template.id}`}
        onClick={()=>onTemplate(template.id)} style={{textAlign:'left',padding:8,border:'1px solid #cbd5e1',borderRadius:6,background:'#fff'}}>
        <strong>{template.title}</strong><span style={{display:'block',fontSize:11,color:'#475569'}}>{template.description}</span>
      </button>)}
      <p style={{margin:0,fontSize:11,color:'#9a3412'}}>Шаблоны не запускают агента. Для каждого Agent нужно указать модель и tool-policy; публикация графа — отдельная функциональность.</p>
      {NODE_TYPES.map((type) => (
        <PaletteItem key={type} type={type} />
      ))}
    </aside>
  );
}
