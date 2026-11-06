/** Local UX preflight only. The orchestration server recompiles immutable snapshots. */
import type { WorkflowDefinition, WorkflowNode } from '../workflow/types';
import type { TaskSpec } from '../api/types';
import { validateWorkflowDocument } from './importExport';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export interface GraphPreview { errors: string[]; tasks: TaskSpec[]; }

export function compilePreview(definition: WorkflowDefinition): GraphPreview {
  const errors = validateWorkflowDocument(definition).errors.map((item) => `${item.path}: ${item.message}`);
  const tasks: TaskSpec[] = [];
  if (definition.schema_version !== '1.0') errors.push('Неподдерживаемая версия схемы');
  const nodes = definition.nodes;
  const edges = definition.edges;
  if (nodes.length < 4 || nodes.length > 80 || edges.length !== nodes.length - 1) {
    errors.push('Нужен линейный граф Start → (Agent → automatic Gate)+ → End');
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  if (byId.size !== nodes.length) errors.push('Повторяющиеся ID нод');
  const incoming = new Map(nodes.map((n) => [n.id, 0]));
  const outgoing = new Map(nodes.map((n) => [n.id, [] as string[]]));
  for (const node of nodes) {
    if (!['start','agent','gate','end'].includes(node.type)) {
      errors.push(`Нода «${node.label}»: тип ${node.type} пока не поддерживается runtime`);
    }
    if (!node.label.trim() || node.label.length > 255) errors.push(`Некорректное имя ноды ${node.id}`);
    if ((node.type === 'start' || node.type === 'end') && Object.keys(node.config).length) {
      errors.push(`Нода ${node.id}: настройки Start/End не исполняются`);
    }
  }
  for (const edge of edges) {
    if (Object.prototype.hasOwnProperty.call(edge, 'condition') || Object.keys(edge.output_mapping ?? {}).length ||
        edge.on_error !== 'fail' || edge.max_retries !== 0) {
      errors.push(`Связь ${edge.id}: условия, output mapping и retry не поддерживаются`);
    }
    if (outgoing.has(edge.source_node_id) && incoming.has(edge.target_node_id)) {
      outgoing.get(edge.source_node_id)!.push(edge.target_node_id);
      incoming.set(edge.target_node_id, (incoming.get(edge.target_node_id) ?? 0) + 1);
    }
  }
  const starts = nodes.filter((n) => n.type === 'start');
  const ends = nodes.filter((n) => n.type === 'end');
  if (starts.length !== 1 || ends.length !== 1) errors.push('Требуется один Start и один End');
  const startId = starts[0]?.id, endId = ends[0]?.id;
  for (const node of nodes) {
    if (incoming.get(node.id) !== (node.id === startId ? 0 : 1) ||
        outgoing.get(node.id)?.length !== (node.id === endId ? 0 : 1)) {
      errors.push(`Нода ${node.id}: ветвления, слияния и разрывы пока не исполняются`);
    }
  }
  if (errors.length || !startId || !endId) return {errors,tasks:[]};
  const visited = new Set([startId]);
  let current = startId;
  while (current !== endId && visited.size <= nodes.length) {
    current = outgoing.get(current)?.[0] ?? '';
    if (!current || visited.has(current)) { errors.push('Цикл или разрыв графа'); break; }
    visited.add(current);
    if (current === endId) break;
    const agent: WorkflowNode | undefined = byId.get(current);
    if (!agent || agent.type !== 'agent') {errors.push('Каждый шаг должен начинаться с Agent');break;}
    const config = agent.config;
    const configKeys = Object.keys(config);
    if (configKeys.length !== 3 ||
      !['agent_definition_id','model_profile_id','tool_policy_id'].every((key) =>
        typeof config[key] === 'string' && UUID.test(config[key] as string))) {
      errors.push(`Agent ${agent.id}: укажите действительные UUID агента, модели и tool-policy без неподдерживаемых настроек`);
      break;
    }
    const gateId = outgoing.get(current)?.[0];
    if (!gateId || visited.has(gateId)) { errors.push('После Agent обязателен Gate'); break; }
    const gate = byId.get(gateId);
    if (!gate || gate.type !== 'gate' || gate.config.gate_type !== 'automatic' ||
      typeof gate.config.contract_id !== 'string' || !UUID.test(gate.config.contract_id) ||
      Object.keys(gate.config).length !== 2) {
      errors.push(`После Agent ${agent.id} нужен automatic Gate с UUID контракта`);
      break;
    }
    visited.add(gateId);
    tasks.push({
      title: agent.label.trim(),
      node_id: agent.id,
      description: `Published graph agent: ${agent.id}`,
      contract_id: gate.config.contract_id,
      input_data: {workflow_node_id:agent.id,workflow_agent_reference:config},
      depends_on: tasks.length ? [tasks.length - 1] : [],
    });
    current = gateId;
  }
  if (!errors.length && (current !== endId || visited.size !== nodes.length || !tasks.length)) {
    errors.push('Все узлы должны составлять единую последовательность Agent → Gate');
  }
  return {errors,tasks:errors.length?[]:tasks};
}
