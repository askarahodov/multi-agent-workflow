/** Guard the editor against successful-looking but mismatched server DTOs.
 * These checks are additive; backend CAS, RBAC and immutable publication
 * remain authoritative. Never trust an HTTP status code alone. */
import type {WorkflowDefinition} from '../workflow/types';
import type {WorkflowDefinitionDTO,WorkflowVersionDTO} from '../api/types';

function normalized(value:unknown):unknown{
  if(Array.isArray(value))return value.map(normalized);
  if(value!==null&&typeof value==='object'){
    const record=value as Record<string,unknown>;
    return Object.fromEntries(Object.keys(record).sort().map(key=>[key,normalized(record[key])]));
  }
  return value;
}
export function sameDocument(left:unknown,right:unknown):boolean{
  if(!left||!right||typeof left!=='object'||typeof right!=='object')return false;
  return JSON.stringify(normalized(left))===JSON.stringify(normalized(right));
}
export function verifyWorkflowReceipt(value:WorkflowDefinitionDTO,{
  projectId,expectedId,expectedSnapshot,previousVersion,allowLegacyGlobal=false,
}:{
  projectId:string;expectedId?:string;expectedSnapshot?:WorkflowDefinition;
  previousVersion?:number;allowLegacyGlobal?:boolean;
}):void{
  if(!value||typeof value.id!=='string'||!value.id ||
     (expectedId!==undefined&&value.id!==expectedId) ||
     (value.project_id!==projectId && !(allowLegacyGlobal&&value.project_id==null)) ||
     !Number.isSafeInteger(value.version)||value.version<1 ||
     (previousVersion!==undefined&&value.version<=previousVersion) ||
     !value.definition || !Array.isArray(value.definition.nodes) ||
     !Array.isArray(value.definition.edges) ||
     typeof value.definition.metadata?.name!=='string' ||
     (expectedSnapshot!==undefined&&!sameDocument(value.definition,expectedSnapshot))){
    throw new Error('Сервер не подтвердил ID проекта, ревизию или снимок workflow; откройте серверный workflow заново.');
  }
}
export function verifyPublishedReceipt(value:WorkflowVersionDTO,{
  definitionId,snapshot,
}:{
  definitionId:string;snapshot?:WorkflowDefinition;
}):void{
  if(!value||typeof value.id!=='string'||!value.id||
     value.workflow_definition_id!==definitionId ||
     !Number.isSafeInteger(value.version_number)||value.version_number<1 ||
     !value.definition_snapshot||typeof value.definition_snapshot!=='object'||
     !Array.isArray(value.definition_snapshot.nodes) ||
     !Array.isArray(value.definition_snapshot.edges) ||
     (snapshot!==undefined&&!sameDocument(value.definition_snapshot,snapshot))){
    throw new Error('Сервер не подтвердил опубликованный immutable snapshot; откройте workflow заново.');
  }
}
