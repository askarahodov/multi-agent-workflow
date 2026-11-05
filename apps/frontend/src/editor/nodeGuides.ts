/** User-facing node semantics. This describes design intent, NOT runtime support. */
import type { NodeType, WorkflowDefinition, WorkflowNode, WorkflowEdge } from '../workflow/types';
import { SCHEMA_VERSION } from '../workflow/types';

export type NodeHelp = {
  title: string;
  purpose: string;
  when: string;
  inputs: string;
  outputs: string;
  configure: string;
  example: string;
  runtime: 'draft';
};
/** No editor graph is currently executable: the graph compiler/publisher is #253. */
export const NODE_HELP: Record<NodeType, NodeHelp> = {
  start: {title:'Начало',purpose:'Единственная входная точка схемы.',when:'Всегда первой нодой; получает входные данные будущего запуска.',inputs:'Данные запуска.',outputs:'Передаёт начальные данные следующей ноде.',configure:'Своих параметров не имеет; изменяется только подпись.',example:'Начало → Исследователь → Конец.',runtime:'draft'},
  agent: {title:'AI-агент',purpose:'Логический исполнитель с выбранной ролью, моделью и политикой инструментов.',when:'Когда требуется анализ, генерация кода, тестирование или обзор.',inputs:'Задача и контекст предыдущих шагов.',outputs:'Результат агента для следующих шагов/контракта.',configure:'Выбери реальное определение агента, профиль модели и tool policy. Все три ссылки обязательны.',example:'Агент «Архитектор» передаёт план агенту «Разработчик».',runtime:'draft'},
  condition: {title:'Условие',purpose:'Определяет развилку по результатам предыдущего шага.',when:'Когда путь зависит от проверки результата.',inputs:'Поля входного результата.',outputs:'Путь true/false по выражению.',configure:'Укажи выражение и настрой подписанные переходы. Язык выражений и маршрутизация ещё не реализованы.',example:'Если тесты успешны → review, иначе → исправление (без циклов).',runtime:'draft'},
  gate: {title:'Проверка / Contract Gate',purpose:'Контроль структуры и допустимости результата.',when:'Перед передачей результата следующему исполнителю.',inputs:'Результат шага и контракт.',outputs:'Подтверждение или отказ.',configure:'Укажи ID контракта и тип проверки. Исполняемый графовый gate ещё не подключён.',example:'Проверить наличие обязательного поля summary.',runtime:'draft'},
  parallel: {title:'Параллельные ветви',purpose:'Разделяет поток для независимых работ.',when:'Если задачи можно выполнять независимо.',inputs:'Общий контекст.',outputs:'Несколько ветвей к Join.',configure:'Нужно соединить с ветками и Join. Исполнение ветвей графа пока не поддержано.',example:'Документация и тесты одновременно.',runtime:'draft'},
  join: {title:'Слияние',purpose:'Собирает результаты параллельных ветвей.',when:'После Parallel, перед итоговой проверкой.',inputs:'Результаты нескольких путей.',outputs:'Общий результат.',configure:'Соедини все входящие ветви; правило завершения пока не исполняется.',example:'Объединить документы и тесты перед релизом.',runtime:'draft'},
  human_approval: {title:'Согласование человеком',purpose:'Планируемый обязательный ручной checkpoint.',when:'Перед релизом, публикацией или рискованным действием.',inputs:'Артефакт и сведения для проверки.',outputs:'Одобрено/отклонено.',configure:'Авторизация и список согласующих должны быть в backend; подписи на схеме недостаточно.',example:'Руководитель подтверждает выпуск релиза.',runtime:'draft'},
  tool: {title:'Инструмент',purpose:'Внешнее действие в пределах политики инструментов.',when:'Для чтения файлов, Git и разрешённых API.',inputs:'Имя инструмента и аргументы.',outputs:'Результат инструмента.',configure:'Имя и параметры JSON; backend обязан применить allowlist. Выполнение этого типа узла ещё не подключено.',example:'Вызвать git status в разрешённом workspace.',runtime:'draft'},
  memory: {title:'Память / контекст',purpose:'Сохранение или получение контекста требуемой области.',when:'Когда несколько шагов обмениваются накопленным контекстом.',inputs:'Данные и область хранения.',outputs:'Извлечённый контекст.',configure:'Выбери scope; хранилище и жизненный цикл ещё не подключены к графу.',example:'Сохранить технические решения проекта.',runtime:'draft'},
  delay: {title:'Ожидание',purpose:'Предполагаемая пауза между этапами.',when:'Для задержек и ограничений частоты.',inputs:'Длительность.',outputs:'Продолжение после ожидания.',configure:'Delay в миллисекундах; графовый таймер ещё не исполняется.',example:'Выдержать паузу перед повторной диагностикой.',runtime:'draft'},
  end: {title:'Завершение',purpose:'Выходная точка схемы.',when:'В конце каждого возможного пути.',inputs:'Финальный результат.',outputs:'Окончание проектируемого процесса.',configure:'Своих параметров не имеет; изменяется только подпись.',example:'После финальной проверки вернуть артефакт.',runtime:'draft'},
};

export const DRAFT_TEMPLATES = [
  {id:'simple',title:'Простой агент',description:'Начало → один агент → конец',stages:['Разработчик']},
  {id:'review',title:'Разработка + проверка',description:'Начало → разработчик → независимый проверяющий → конец',stages:['Разработчик','Проверяющий']},
  {id:'sdlc',title:'Семь стадий SDLC',description:'Исследование → архитектура → реализация → тесты → review → security → подготовка релиза',stages:['Исследователь','Архитектор','Разработчик','Тестировщик','Ревьюер','Security','Подготовка релиза']},
] as const;

export type TemplateId = typeof DRAFT_TEMPLATES[number]['id'];

/** Deliberately leave required agent references unset: no fake UUIDs or runnable claims. */
export function buildDraftTemplate(id: TemplateId): WorkflowDefinition {
  const template = DRAFT_TEMPLATES.find(t => t.id === id)!;
  const start: WorkflowNode = {id:'start',type:'start',label:'Начало',position:{x:0,y:100},config:{}};
  const middle: WorkflowNode[] = template.stages.map((stage,i) => ({
    id:`agent-${i+1}`,type:'agent',label:stage,position:{x:(i+1)*230,y:100},config:{},
  }));
  const end: WorkflowNode = {id:'end',type:'end',label:'Конец',position:{x:(middle.length+1)*230,y:100},config:{}};
  const nodes = [start,...middle,end];
  const edges: WorkflowEdge[] = nodes.slice(0,-1).map((node,i)=>({
    id:`edge-${i+1}`,source_node_id:node.id,target_node_id:nodes[i+1].id,
    output_mapping:{},on_error:'fail',max_retries:0,
  }));
  return {schema_version:SCHEMA_VERSION,metadata:{name:template.title,description:template.description,version:1,created_at:new Date().toISOString()},nodes,edges};
}
