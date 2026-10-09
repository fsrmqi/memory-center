import { ref } from 'vue'
export const token = ref('')
export const notice = ref('')
export const failure = ref('')
export type Item = { id: string; revision: number; title?: string; content?: string; status?: string; [key: string]: any }
export type Workspace = { workspace_id: string; name: string; root: string; status: string; revision: number; index_status?: string; generation?: string; services: {service_id:string;name:string;path:string;type:string}[] }
export async function api(path: string, method = 'GET', body?: unknown) {
  const payload = body === undefined && ['POST','PUT','PATCH'].includes(method) ? {} : body
  const response = await fetch('/api/v1' + path, {
    method, headers: { Authorization: 'Bearer ' + token.value, ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(120000),
  })
  const value = await response.json()
  if (!response.ok) throw new Error(value.error?.message || '请求失败，请重试')
  return value
}
export async function action(task: () => Promise<void>, message = '操作完成') {
  failure.value = ''; notice.value = ''
  try { await task(); notice.value = message } catch (error) { failure.value = error instanceof Error ? error.message : '操作失败' }
}
export const states: Record<string, string> = { ready:'可查询',stale:'需重建',not_indexed:'未索引',active:'已接入', paused:'已暂停', queued:'排队中',running:'索引中',succeeded:'成功',failed:'失败',cancelled:'已取消',interrupted:'已中断',confirmed:'已确认',pending:'待确认',rejected:'已拒绝',deleted:'已移除' }
