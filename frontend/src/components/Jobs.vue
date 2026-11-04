<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, action, states, type Item } from '../api'
import Pagination from './Pagination.vue'
import {readDraft,storeDraft,removeDraft} from '../drafts'
import {confirmAction} from '../confirmation'
import {readRoute,rememberRoute,routeNumber,leaveGuards} from '../navigation'
import KnowledgeGovernance from './KnowledgeGovernance.vue'
const emit = defineEmits<{ storage: [] }>()
const route=readRoute()
const detailPanel=ref<HTMLElement|null>(null)
const taskType=ref(route.params.get('type')==='knowledge'?'knowledge':'index'),detail=ref<any>(null),preview=ref<any>(null),previewTitle=ref(''),previewContent=ref('')
const fixes:Record<string,string>={manual_retry:'处理原因后手动重试',check_model:'检查模型连接与配置',inspect_storage:'检查图数据库及磁盘',inspect_resources:'检查目录权限和可用内存'}
const previewPage=ref(1),previewPages=computed(()=>Math.max(1,Math.ceil((detail.value?.preview_ids?.length||0)/10))),visiblePreviews=computed(()=>(detail.value?.preview_ids||[]).slice((previewPage.value-1)*10,previewPage.value*10))
const clock=ref(Date.now()),pending=ref(new Set<string>())
const active=(item:any)=>['queued','running'].includes(item.status)
function timestamp(value:string){const date=new Date(value);return value&&Number.isFinite(date.getTime())?date.toLocaleString('zh-CN',{hour12:false}):'—'}
function duration(item:any){if(!item.started_at)return '未开始';const start=Date.parse(item.started_at),end=item.finished_at?Date.parse(item.finished_at):active(item)?clock.value:NaN;if(!Number.isFinite(start)||!Number.isFinite(end))return '结束时间未记录';const seconds=Math.max(0,Math.floor((end-start)/1000));return `${Math.floor(seconds/3600)} 小时 ${Math.floor(seconds%3600/60)} 分 ${seconds%60} 秒`}
function terminalTime(item:any){return item.finished_at?timestamp(item.finished_at):active(item)?'未结束':'未记录'}
let detailSequence=0
async function inspect(item:Item){if(!await leaveReview())return;const request=++detailSequence,kind=taskType.value;previewPage.value=1;preview.value=null;rememberRoute({task:item.id,type:kind});const result=kind==='knowledge'?await api(`/knowledge-tasks/${item.id}`):item;if(request===detailSequence&&kind===taskType.value){detail.value=result;await nextTick();detailPanel.value?.scrollIntoView({behavior:'smooth',block:'start'})}}
async function closeDetails(){if(!await leaveReview())return;detailSequence++;detail.value=null;preview.value=null;rememberRoute({task:''})}
async function viewPreview(id:string){if(!await leaveReview())return;const task=detail.value;if(!task)return;const draft=await api(`/workspaces/${task.workspace_id}/organize/${id}`);if(detail.value?.id!==task.id)return;preview.value=draft;const saved=readDraft(reviewKey());previewTitle.value=saved?.revision===draft.revision?saved.title:draft.title;previewContent.value=saved?.revision===draft.revision?saved.content:draft.content}
async function applyPreview(){await action(async()=>{await api(`/workspaces/${detail.value.workspace_id}/organize/${preview.value.id}/apply`,'POST',{revision:preview.value.revision,title:previewTitle.value,content:previewContent.value});removeDraft(reviewKey());preview.value=null},preview.value?.kind==='memory'?'整理结果已保存，记忆需另行确认':'整理结果已保存')}
watch(taskType,()=>{detailSequence++;detail.value=null;preview.value=null;rememberRoute({type:taskType.value});action(()=>load(1),'')})
const page=ref(routeNumber('page',1)),pageSize=ref(routeNumber('size',10,[10,20,50])),pages=ref(1),total=ref(0),filter=ref(route.params.get('q')||''),status=ref(route.params.get('status')||''),appliedFilter=ref(route.params.get('q')||''),appliedStatus=ref(route.params.get('status')||''),loading=ref(false)
let sequence=0
async function load(target=page.value){const request=++sequence;loading.value=true;try{const data=await api((taskType.value==='knowledge'?'/knowledge-tasks?':'/jobs?')+new URLSearchParams({page:String(target),page_size:String(pageSize.value),q:appliedFilter.value,status:appliedStatus.value}));if(request!==sequence)return;items.value=data.items;void resolveProjects(data.items);if(detail.value){const fresh=data.items.find((i:Item)=>i.id===detail.value.id);if(fresh)detail.value=fresh}page.value=data.page;pages.value=data.pages;total.value=data.total;rememberRoute({page:data.page,size:pageSize.value,q:appliedFilter.value,status:appliedStatus.value,type:taskType.value})}finally{if(request===sequence)loading.value=false}}
async function applyFilter(){appliedFilter.value=filter.value;appliedStatus.value=status.value;await action(()=>load(1),'')}
const items = ref<Item[]>([])
const projectNames=ref<Record<string,string>>({})
async function resolveProjects(rows:Item[]){await Promise.all([...new Set(rows.map(row=>row.workspace_id))].filter(id=>id&&!projectNames.value[id]).map(async id=>{try{const project=await api(`/workspaces/${id}`);projectNames.value[id]=project.name}catch{projectNames.value[id]=id}}))}
const phases:Record<string,string>={queued:'等待调度',scanning:'扫描源码',chunking:'源码分块',parsing:'解析代码',relations:'解析调用关系',services:'服务专用分析',knowledge:'读取知识',embedding:'向量化',publishing:'发布索引'}
const units:Record<string,string>={files:'文件',services:'服务',chunks:'分块',items:'条目'}
async function refresh() {
  await action(async () => { await load() }, '任务状态已更新')
}
async function operation(item: Item, op: string) {
  if(pending.value.has(item.id))return
  pending.value.add(item.id)
  try{await action(async () => {
    await api(`/${taskType.value==='knowledge'?'knowledge-tasks':'jobs'}/${item.id}/${op}`, 'POST')
    await load()
  },op==='retry'?'已创建新任务；失败后仍需手动重试':'已请求取消；上一代索引保留')}finally{pending.value.delete(item.id)}
}
async function remove(item: Item) {
  if(pending.value.has(item.id)||!window.confirm('删除这条任务记录？已发布索引不会删除。'))return
  pending.value.add(item.id)
  try{await action(async () => {
    await api(`/jobs/${item.id}`, 'DELETE')
    await load()
  }, '任务已删除；旧索引可在项目存储治理中预览后清理')}finally{pending.value.delete(item.id)}
}
function prune() {
  emit('storage')
}
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  action(async()=>{await load();const id=route.params.get('task');if(id){const task=taskType.value==='knowledge'?await api('/knowledge-tasks/'+encodeURIComponent(id)):(await api('/jobs?q='+encodeURIComponent(id)+'&page_size=10')).items.find((i:Item)=>i.id===id);if(task)await inspect(task);else throw new Error('任务记录已不存在，请查看任务列表')}},'')
  timer = setInterval(async () => {
    clock.value=Date.now()
    try { if(!loading.value)await load() } catch { /* 轮询失败不打断页面 */ }
  }, 3000)
})
onUnmounted(() => {sequence++;clearInterval(timer)})
function reviewKey(){return `memory-center:task-review:${detail.value?.workspace_id}:${preview.value?.id}`}
const reviewDirty=computed(()=>!!preview.value&&(previewTitle.value!==preview.value.title||previewContent.value!==preview.value.content))
watch([previewTitle,previewContent],()=>{if(reviewDirty.value&&!storeDraft(reviewKey(),{title:previewTitle.value,content:previewContent.value,revision:preview.value.revision}))noticeReview.value='浏览器无法保留整理稿，请及时保存。'})
const noticeReview=ref('')
function leaveReview(){return !reviewDirty.value||confirmAction('整理稿尚未保存，修改会保留在当前标签页。','保留草稿并离开')}
function unloadReview(event:BeforeUnloadEvent){if(reviewDirty.value){event.preventDefault();event.returnValue=''}}
leaveGuards.add(leaveReview);window.addEventListener('beforeunload',unloadReview)
onUnmounted(()=>{leaveGuards.delete(leaveReview);window.removeEventListener('beforeunload',unloadReview)})
async function switchTaskType(event:Event){const next=(event.target as HTMLSelectElement).value;if(await leaveReview())taskType.value=next;else (event.target as HTMLSelectElement).value=taskType.value}
</script>
<template>
  <div class="page-title">
    <div><h1>后台任务</h1><p>显示当前阶段的真实完成量；项目并发可在模型设置中调整。取消和失败保留上一代可用索引。</p></div>
    <div class="actions">
      <button @click="refresh">刷新</button>
      <button @click="prune">项目存储治理</button>
    </div>
  </div>
  <label>任务类型<select :value="taskType" @change="switchTaskType"><option value="index">项目索引</option><option value="knowledge">知识任务</option></select></label>
  <form class="toolbar" @submit.prevent="applyFilter"><input v-model="filter" aria-label="筛选任务" placeholder="搜索任务或项目 ID"><select v-model="status" aria-label="任务状态" @change="applyFilter"><option value="">全部状态</option><option v-for="s in ['queued','running','succeeded','failed','cancelled','interrupted']" :key="s" :value="s">{{states[s]}}</option></select><button>筛选</button></form>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>任务</th><th>项目</th><th>状态</th><th>进度</th><th>时间与耗时</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id">
          <td class="mono">{{item.id}}<small class="error" v-if="item.error">{{item.error}} {{item.message}}</small></td>
          <td class="task-project"><strong>{{projectNames[item.workspace_id]||item.workspace_id}}</strong><small class="mono">{{item.workspace_id}}</small></td>
          <td><span class="state">{{taskType==='knowledge'&&item.status==='running'?(item.operation==='governance'?'治理中':item.kind==='refresh'?'刷新中':'整理中'):states[item.status||'']}}</span></td>
          <td><template v-if="taskType==='knowledge'">{{item.operation==='governance'?'智能治理':item.kind==='refresh'?'知识刷新':'内容整理'}} · {{item.completed}} / {{item.total}} {{item.operation==='governance'&&item.phase!=='summarizing'?'对来源':item.kind==='refresh'?'分块':'条来源'}} · {{item.preview_ids?.length||0}} 个生成预览</template><template v-else-if="item.status==='succeeded'">已完成 · 100%</template><template v-else-if="item.progress_scope==='phase'"><strong>{{phases[item.phase]||item.phase}}</strong><div><progress v-if="item.total" max="100" :value="item.progress"></progress><progress v-else-if="item.status==='running'" max="100"></progress> {{item.total ? `${item.completed} / ${item.total} ${units[item.unit]||''} · 阶段 ${item.progress}%` : `${item.completed||0} ${units[item.unit]||''} · 总量待确定`}}</div><small>{{item.detail}}</small><small v-if="item.started_at">已用时 {{Math.max(0,Math.round((Date.parse(item.finished_at||new Date().toISOString())-Date.parse(item.started_at))/1000))}} 秒</small></template><template v-else>旧任务阶段记录 · {{item.progress}}%</template></td>
          <td class="task-time"><small>开始：{{item.started_at?timestamp(item.started_at):'未开始'}}</small><small>结束：{{terminalTime(item)}}</small><strong>处理：{{duration(item)}}</strong></td>
          <td class="actions"><button :aria-expanded="detail?.id===item.id" @click="inspect(item)">详情</button>
            <button v-if="['queued','running'].includes(item.status||'')" :disabled="pending.has(item.id)" @click="operation(item,'cancel')">取消</button>
            <button v-if="['failed','cancelled','interrupted'].includes(item.status||'')" :disabled="pending.has(item.id)" @click="operation(item,'retry')">重试</button>
            <button v-if="taskType==='index'&&['failed','cancelled','interrupted','succeeded'].includes(item.status||'')" class="danger" :disabled="pending.has(item.id)" @click="remove(item)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <Pagination :page="page" :page-size="pageSize" :total="total" :pages="pages" label="后台任务" :busy="loading" @change="action(()=>load($event),'')" @size="pageSize=$event;action(()=>load(1),'')"/>
  <section v-if="detail" ref="detailPanel" class="form-panel"><div class="panel-heading"><h2>任务详情</h2><button @click="closeDetails">关闭</button></div><p class="mono">{{detail.id}}</p><div class="task-summary"><p>创建时间：{{timestamp(detail.created_at)}}</p><p>开始时间：{{detail.started_at?timestamp(detail.started_at):'未开始'}}</p><p>结束时间：{{terminalTime(detail)}}</p><p>总处理时间：{{duration(detail)}}</p></div><p v-if="detail.incremental">服务事实：{{{full:'完整构建',incremental:'增量构建',unchanged:'复用基线'}[detail.incremental.mode as string]}} · 复用 {{detail.incremental.reused_services?.length||0}} 个服务 · 分析 {{detail.incremental.changed_services?.length||0}} 个服务 · 新增 {{detail.incremental.added_files}}／修改 {{detail.incremental.modified_files}}／删除 {{detail.incremental.deleted_files}} 文件</p><p v-if="detail.diagnostics" class="error">{{detail.diagnostics.code}} · {{detail.diagnostics.phase}} · 诊断标识 {{detail.diagnostics.trace_id}}</p><p v-for="fix in detail.diagnostics?.supported_fixes||[]" :key="fix">{{fixes[fix]||fix}}</p><ul><li v-for="(event,i) in detail.events||[]" :key="i">{{phases[event.phase]||event.phase}} · {{timestamp(event.started_at)}} · 距任务开始 {{event.elapsed_seconds}} 秒</li></ul><p v-if="detail.model_metrics" class="muted">嵌入请求 {{detail.model_metrics.requests}} 次 · 请求累计耗时 {{Number(detail.model_metrics.request_seconds).toFixed(2)}} 秒（并发时可大于阶段耗时） · 输入 Token {{detail.model_metrics.input_tokens??'未提供完整用量'}}</p><p v-if="detail.duplicate_groups?.length">发现 {{detail.duplicate_groups.length}} 组重复来源，原文保留。</p><button v-for="id in detail.operation==='governance'?[]:visiblePreviews" :key="id" @click="viewPreview(id)">审阅 {{id}}</button>
  <KnowledgeGovernance v-if="detail.operation==='governance'" :workspace="detail.workspace_id" :kind="detail.kind"/><div v-if="detail.operation!=='governance'&&previewPages>1" class="actions"><button :disabled="previewPage===1" @click="previewPage--">上一页预览</button><span>{{previewPage}} / {{previewPages}}</span><button :disabled="previewPage===previewPages" @click="previewPage++">下一页预览</button></div><p v-if="noticeReview" class="error">{{noticeReview}}</p><form v-if="preview" @submit.prevent="applyPreview"><h3>整理预览 · {{preview.model}}</h3><p class="muted">{{preview.sources.length}} 条来源；来源修订变化后不能保存。模型耗时 {{preview.metrics?.duration_seconds??'未提供'}} 秒，输入／输出 Token {{preview.metrics?.input_tokens??'未提供'}} / {{preview.metrics?.output_tokens??'未提供'}}</p><label>标题<input v-model="previewTitle" required maxlength="200"></label><label>正文<textarea v-model="previewContent" required rows="12" maxlength="200000"></textarea></label><button v-if="preview.status==='preview'" class="primary">确认保存整理结果</button><p v-else>此预览已保存。</p></form></section>
  <p v-if="!items.length" class="empty">{{appliedFilter||appliedStatus?'没有匹配的任务，可清除筛选后查看。':taskType==='knowledge'?'还没有知识任务，可在 Wiki 或记忆页面启动整理或智能治理。':'还没有索引任务，可在项目页面启动索引。'}}</p>
</template>

<style scoped>
.task-project small{display:block;margin-top:6px;color:#667085}.actions button{white-space:nowrap;flex-shrink:0}td.actions{min-width:150px}.form-panel{max-width:none;width:100%;box-sizing:border-box}.task-time{min-width:225px;white-space:nowrap}.task-time small{display:block;line-height:1.8}.task-time strong{font-size:12px}.task-summary{display:grid;grid-template-columns:1fr 1fr;gap:0 24px;background:var(--surface-alt,#f5f7fb);padding:12px 20px;border-radius:12px}.task-summary p{margin:6px 0}
</style>
