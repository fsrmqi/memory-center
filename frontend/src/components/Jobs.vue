<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, action, states, type Item } from '../api'
import Pagination from './Pagination.vue'
const emit = defineEmits<{ storage: [] }>()
const taskType=ref('index'),detail=ref<any>(null),preview=ref<any>(null),previewTitle=ref(''),previewContent=ref('')
const fixes:Record<string,string>={manual_retry:'处理原因后手动重试',check_model:'检查模型连接与配置',inspect_storage:'检查图数据库及磁盘',inspect_resources:'检查目录权限和可用内存'}
const previewPage=ref(1),previewPages=computed(()=>Math.max(1,Math.ceil((detail.value?.preview_ids?.length||0)/10))),visiblePreviews=computed(()=>(detail.value?.preview_ids||[]).slice((previewPage.value-1)*10,previewPage.value*10))
let detailSequence=0
async function inspect(item:Item){const request=++detailSequence,kind=taskType.value;previewPage.value=1;preview.value=null;const result=kind==='knowledge'?await api(`/knowledge-tasks/${item.id}`):item;if(request===detailSequence&&kind===taskType.value)detail.value=result}
function closeDetails(){detailSequence++;detail.value=null;preview.value=null}
async function viewPreview(id:string){const task=detail.value;if(!task)return;const draft=await api(`/workspaces/${task.workspace_id}/organize/${id}`);if(detail.value?.id!==task.id)return;preview.value=draft;previewTitle.value=draft.title;previewContent.value=draft.content}
async function applyPreview(){await action(async()=>{await api(`/workspaces/${detail.value.workspace_id}/organize/${preview.value.id}/apply`,'POST',{revision:preview.value.revision,title:previewTitle.value,content:previewContent.value});preview.value=null},preview.value?.kind==='memory'?'整理结果已保存，记忆需另行确认':'整理结果已保存')}
watch(taskType,()=>{closeDetails();action(()=>load(1),'')})
const page=ref(1),pageSize=ref(10),pages=ref(1),total=ref(0),filter=ref(''),status=ref(''),appliedFilter=ref(''),appliedStatus=ref(''),loading=ref(false)
let sequence=0
async function load(target=page.value){const request=++sequence;loading.value=true;try{const data=await api((taskType.value==='knowledge'?'/knowledge-tasks?':'/jobs?')+new URLSearchParams({page:String(target),page_size:String(pageSize.value),q:appliedFilter.value,status:appliedStatus.value}));if(request!==sequence)return;items.value=data.items;if(detail.value){const fresh=data.items.find((i:Item)=>i.id===detail.value.id);if(fresh)detail.value=fresh}page.value=data.page;pages.value=data.pages;total.value=data.total}finally{if(request===sequence)loading.value=false}}
async function applyFilter(){appliedFilter.value=filter.value;appliedStatus.value=status.value;await action(()=>load(1),'')}
const items = ref<Item[]>([])
const phases:Record<string,string>={queued:'等待调度',scanning:'扫描源码',chunking:'源码分块',parsing:'解析代码',relations:'解析调用关系',services:'服务专用分析',knowledge:'读取知识',embedding:'向量化',publishing:'发布索引'}
const units:Record<string,string>={files:'文件',services:'服务',chunks:'分块',items:'条目'}
async function refresh() {
  await action(async () => { await load() }, '任务状态已更新')
}
async function operation(item: Item, op: string) {
  await action(async () => {
    await api(`/${taskType.value==='knowledge'?'knowledge-tasks':'jobs'}/${item.id}/${op}`, 'POST')
    await load()
  })
}
async function remove(item: Item) {
  await action(async () => {
    await api(`/jobs/${item.id}`, 'DELETE')
    await load()
  }, '任务已删除；旧索引可在项目存储治理中预览后清理')
}
function prune() {
  emit('storage')
}
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  refresh()
  timer = setInterval(async () => {
    try { if(!loading.value)await load() } catch { /* 轮询失败不打断页面 */ }
  }, 3000)
})
onUnmounted(() => {sequence++;clearInterval(timer)})
</script>
<template>
  <div class="page-title">
    <div><h1>后台任务</h1><p>显示当前阶段的真实完成量；项目并发可在模型设置中调整。取消和失败保留上一代可用索引。</p></div>
    <div class="actions">
      <button @click="refresh">刷新</button>
      <button @click="prune">项目存储治理</button>
    </div>
  </div>
  <label>任务类型<select v-model="taskType"><option value="index">项目索引</option><option value="knowledge">知识任务</option></select></label>
  <form class="toolbar" @submit.prevent="applyFilter"><input v-model="filter" aria-label="筛选任务" placeholder="搜索任务或项目 ID"><select v-model="status" aria-label="任务状态" @change="applyFilter"><option value="">全部状态</option><option v-for="s in ['queued','running','succeeded','failed','cancelled','interrupted']" :key="s" :value="s">{{states[s]}}</option></select><button>筛选</button></form>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>任务</th><th>项目</th><th>状态</th><th>进度</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id">
          <td class="mono">{{item.id}}<small class="error" v-if="item.error">{{item.error}} {{item.message}}</small></td>
          <td class="mono">{{item.workspace_id}}</td>
          <td><span class="state">{{taskType==='knowledge'&&item.status==='running'?'整理中':states[item.status||'']}}</span></td>
          <td><template v-if="taskType==='knowledge'">{{item.kind==='refresh'?'知识刷新':'内容整理'}} · {{item.completed}} / {{item.total}} {{item.kind==='refresh'?'分块':'条来源'}} · {{item.preview_ids?.length||0}} 个待审预览</template><template v-else-if="item.status==='succeeded'">已完成 · 100%</template><template v-else-if="item.progress_scope==='phase'"><strong>{{phases[item.phase]||item.phase}}</strong><div><progress v-if="item.total" max="100" :value="item.progress"></progress><progress v-else-if="item.status==='running'" max="100"></progress> {{item.total ? `${item.completed} / ${item.total} ${units[item.unit]||''} · 阶段 ${item.progress}%` : `${item.completed||0} ${units[item.unit]||''} · 总量待确定`}}</div><small>{{item.detail}}</small><small v-if="item.started_at">已用时 {{Math.max(0,Math.round((Date.parse(item.finished_at||new Date().toISOString())-Date.parse(item.started_at))/1000))}} 秒</small></template><template v-else>旧任务阶段记录 · {{item.progress}}%</template></td>
          <td class="actions"><button @click="inspect(item)">详情</button>
            <button v-if="['queued','running'].includes(item.status||'')" @click="operation(item,'cancel')">取消</button>
            <button v-if="['failed','cancelled','interrupted'].includes(item.status||'')" @click="operation(item,'retry')">重试</button>
            <button v-if="taskType==='index'&&['failed','cancelled','interrupted','succeeded'].includes(item.status||'')" class="danger" @click="remove(item)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <Pagination :page="page" :page-size="pageSize" :total="total" :pages="pages" label="后台任务" :busy="loading" @change="action(()=>load($event),'')" @size="pageSize=$event;action(()=>load(1),'')"/>
  <section v-if="detail" class="form-panel"><div class="panel-heading"><h2>任务详情</h2><button @click="closeDetails">关闭</button></div><p>{{detail.id}}</p><p v-if="detail.diagnostics" class="error">{{detail.diagnostics.code}} · {{detail.diagnostics.phase}} · 诊断标识 {{detail.diagnostics.trace_id}}</p><p v-for="fix in detail.diagnostics?.supported_fixes||[]" :key="fix">{{fixes[fix]||fix}}</p><ul><li v-for="(event,i) in detail.events||[]" :key="i">{{phases[event.phase]||event.phase}} · {{event.started_at}} · 累计 {{event.elapsed_seconds}} 秒</li></ul><p v-if="detail.model_metrics" class="muted">嵌入请求 {{detail.model_metrics.requests}} 次 · 请求累计耗时 {{Number(detail.model_metrics.request_seconds).toFixed(2)}} 秒（并发时可大于阶段耗时） · 输入 Token {{detail.model_metrics.input_tokens??'未提供完整用量'}}</p><p v-if="detail.duplicate_groups?.length">发现 {{detail.duplicate_groups.length}} 组重复来源，原文保留。</p><button v-for="id in visiblePreviews" :key="id" @click="viewPreview(id)">审阅 {{id}}</button>
  <div v-if="previewPages>1" class="actions"><button :disabled="previewPage===1" @click="previewPage--">上一页预览</button><span>{{previewPage}} / {{previewPages}}</span><button :disabled="previewPage===previewPages" @click="previewPage++">下一页预览</button></div><form v-if="preview" @submit.prevent="applyPreview"><h3>整理预览 · {{preview.model}}</h3><p class="muted">{{preview.sources.length}} 条来源；来源修订变化后不能保存。模型耗时 {{preview.metrics?.duration_seconds??'未提供'}} 秒，输入／输出 Token {{preview.metrics?.input_tokens??'未提供'}} / {{preview.metrics?.output_tokens??'未提供'}}</p><label>标题<input v-model="previewTitle" required maxlength="200"></label><label>正文<textarea v-model="previewContent" required rows="12" maxlength="200000"></textarea></label><button v-if="preview.status==='preview'" class="primary">确认保存整理结果</button><p v-else>此预览已保存。</p></form></section>
  <p v-if="!items.length" class="empty">没有后台任务。在项目页面启动索引。</p>
</template>
