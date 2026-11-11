import type { CursorPage } from '../api/types';

/**
 * Shared fail-closed catalog pagination for the wizard and the inspector.
 * Never treat the first page or a cyclic/incomplete cursor sequence as a
 * complete list of selectable server-owned agent/model/policy references.
 */
export async function allPages<T>(
  fetchPage:(after?:string)=>Promise<CursorPage<T>>,
):Promise<T[]> {
  const items:T[]=[];
  const seen=new Set<string>();
  let cursor:string|undefined;
  for(let page=0;page<100;page++){
    const response=await fetchPage(cursor);
    if(!Array.isArray(response.items) ||
        (response.next_cursor!=null &&
          (typeof response.next_cursor!=='string'||!response.next_cursor))) {
      throw new Error('Некорректный справочник');
    }
    items.push(...response.items);
    if(!response.next_cursor) return items;
    if(seen.has(response.next_cursor)) throw new Error('Повторный курсор справочника');
    seen.add(response.next_cursor);
    cursor=response.next_cursor;
  }
  throw new Error('Слишком большой справочник — обратитесь к администратору');
}
