<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { action, api, states } from '../api'
import Pagination from './Pagination.vue'
import MarkdownView from './MarkdownView.vue'
const props=defineProps<{workspace:string;kind:'wiki'|'memory'}>()
const emit=defineEmits<{saved:[]}>()
const opened=ref(false),items=ref<any[]>([]),task=ref<any>(null),selected=ref<any>(null)
const page=ref(1),pageSize=ref(10),pages=ref(1),total=ref(0),status=ref('pending'),category=ref(''),pairLimit=ref(500)
const loading=ref(false),busy=ref(false),title=ref(''),content=ref(''),retired=ref<string[]>([]),confirmMemory=ref(false),reviewed=ref(false)
const labels:Record<string,string>={pending:'待审阅',merged:'已合并',kept:'已保留双方',dismissed:'已忽略',duplicate:'语义重复',conflict:'潜在冲突',summarizing:'提取主题',comparing:'核对来源',review:'等待审阅'}
const stale=computed(()=>selected.value?.sources.some((s:any)=>s.stale))
const active=computed(()=>task.value&&['queued','running'].includes(task.value.status))
let sequence=0,timer:ReturnType<typeof setInterval>|undefined
async function load(target=page.value){
 const id=++sequence,w=props.workspace,k=props.kind;loading.value=true
 try{
  const params=new URLSearchParams({kind:k,page:String(target),page_size:String(pageSize.value),status:status.value,category:category.value})
  const [list,latest]=await Promise.all([api(`/workspaces/${w}/knowledge-governance?${params}`),api(`/workspaces/${w}/knowledge-governance/latest?kind=${k}`)])
  if(id!==sequence||w!==props.workspace||k!==props.kind)return
  items.value=list.items;total.value=list.total;pages.value=list.pages;page.value=list.page;task.value=latest.task
 }finally{if(id===sequence)loading.value=false}
}
async function filterSuggestions(){selectionSequence++;selected.value=null;await action(()=>load(1),'')}
async function open(){opened.value=!opened.value;if(opened.value)await action(()=>load(1),'')}
async function scan(){busy.value=true;const w=props.workspace,k=props.kind
 await action(async()=>{const result=await api(`/workspaces/${w}/knowledge-tasks`,'POST',{kind:k,operation:'governance',pair_limit:pairLimit.value});if(w===props.workspace&&k===props.kind){task.value=result;selected.value=null;status.value='pending';await load(1)}},'智能治理已排队，分析完成后逐组审阅')
 busy.value=false
}
async function operate(op:'cancel'|'retry'){const current=task.value;if(!current)return;busy.value=true
 await action(async()=>{await api(`/knowledge-tasks/${current.id}/${op}`,'POST');await load()},op==='cancel'?'分析已取消；原文未改动':'已手动提交新的分析任务');busy.value=false
}
let selectionSequence=0
async function select(item:any){const seq=++selectionSequence,w=props.workspace,k=props.kind,filterState=status.value+category.value;await action(async()=>{const draft=await api(`/workspaces/${w}/knowledge-governance/${item.id}`);if(seq!==selectionSequence||w!==props.workspace||k!==props.kind||filterState!==status.value+category.value)return;selected.value=draft;title.value=draft.title;content.value=draft.content;retired.value=[];confirmMemory.value=false;reviewed.value=false},'')}
async function decide(decision:'merge'|'keep_both'|'dismiss'){
 const draft=selected.value,w=props.workspace,k=props.kind;if(!draft||!reviewed.value||busy.value||(stale.value&&decision!=='dismiss'))return;busy.value=true
 await action(async()=>{await api(`/workspaces/${w}/knowledge-governance/${draft.id}/decision`,'POST',{
 revision:draft.revision,decision,confirm:true,title:decision==='merge'?title.value:'',content:decision==='merge'?content.value:'',
 retire_source_ids:decision==='merge'?retired.value:[],confirm_memory:decision==='merge'&&confirmMemory.value})
 if(w===props.workspace&&k===props.kind){selected.value=null;await load();emit('saved')}},decision==='merge'?'已保存审阅后的合并稿，可刷新知识索引':'处理决定已保存，来源保持原样')
 busy.value=false
}
watch(()=>[props.workspace,props.kind],()=>{sequence++;opened.value=false;items.value=[];task.value=null;selected.value=null;page.value=1;status.value='pending';category.value='';loading.value=false})
timer=setInterval(()=>{if(opened.value&&active.value&&!loading.value&&!busy.value)action(()=>load(),'')},3000)
onUnmounted(()=>{sequence++;clearInterval(timer)})
</script>
<template>
 <section class="governance-panel">
  <div class="panel-heading"><div><h2>智能治理</h2><p class="muted">发现语义重复和潜在冲突，对照来源、编辑合并稿后再保存。</p></div><button class="primary" @click="open" :disabled="!workspace">{{opened?'收起治理':'打开智能治理'}}</button></div>
  <template v-if="opened">
   <div class="governance-controls"><label>本次最多比较的来源对<input v-model.number="pairLimit" type="number" min="1" max="5000" :disabled="busy||active"></label><div class="actions"><button class="primary" @click="scan" :disabled="busy||active">分析全部{{kind==='wiki'?' Wiki':'记忆'}}</button><button @click="action(()=>load(),'')" :disabled="loading">刷新建议</button></div></div>
   <p class="muted">使用普通模型，不需要向量。小库全配对，大库按模型摘要召回候选；未比较的来源不能认定没有重复或冲突。建议有效期 7 天。</p>
   <div v-if="task" class="governance-task" role="status"><div class="panel-heading"><strong>{{states[task.status]}} · {{labels[task.phase]||'等待调度'}}</strong><div class="actions"><button v-if="active" @click="operate('cancel')" :disabled="busy">取消分析</button><button v-if="['failed','cancelled','interrupted'].includes(task.status)" @click="operate('retry')" :disabled="busy">手动重新分析</button></div></div><p>{{task.completed}} / {{task.total}} {{task.phase==='comparing'||task.phase==='review'?'对来源':'条来源'}} · {{task.preview_ids?.length||0}} 条建议</p><p v-if="task.coverage" class="muted">已比较 {{task.coverage.compared_pairs}} / {{task.coverage.possible_pairs}} 个可能来源对 · {{task.coverage.exhaustive?'全配对完成':'候选召回，覆盖非完整'}}{{task.coverage.budget_limited?' · 已达到本次比较预算':''}}</p><p v-if="task.error" class="error">{{task.error}} · {{task.message}}。不会自动重试。</p><p v-if="task.chat_metrics" class="muted">模型请求 {{task.chat_metrics.requests}} 次 · 累计 {{Number(task.chat_metrics.duration_seconds).toFixed(1)}} 秒</p></div>
   <div class="toolbar"><label>建议状态<select v-model="status" aria-label="治理建议状态" @change="filterSuggestions"><option value="pending">待审阅</option><option value="">全部</option><option value="merged">已合并</option><option value="kept">已保留双方</option><option value="dismissed">已忽略</option></select></label><label>建议类型<select v-model="category" aria-label="治理建议类型" @change="filterSuggestions"><option value="">全部类型</option><option value="duplicate">语义重复</option><option value="conflict">潜在冲突</option></select></label></div>
   <div class="governance-layout"><div class="governance-list"><button v-for="item in items" :key="item.id" class="governance-card" :disabled="loading||busy" :class="{chosen:selected?.id===item.id}" @click="select(item)"><div class="panel-heading"><span :class="['governance-badge',item.category]">{{labels[item.category]}}</span><small>{{labels[item.status]}}</small></div><h3>{{item.title}}</h3><p>{{item.reason}}</p><small>模型置信度 {{Math.round(item.confidence*100)}}% · {{item.sources.length}} 条来源</small></button><p v-if="!items.length" class="empty">{{active?'分析完成后将显示待审建议。':'当前筛选下没有建议。可开始分析或切换状态查看。'}}</p></div>
   <div class="governance-reader"><template v-if="selected"><div class="panel-heading"><h3>{{labels[selected.category]}} · 来源对照</h3><button @click="selected=null">关闭审阅</button></div><p v-if="selected.category==='conflict'" class="source-note">这是模型提出的潜在冲突，请核对时间、范围和当前事实；系统不会替你判定哪一方正确。</p><div class="governance-sources"><article v-for="s in selected.sources" :key="s.id"><h4>{{s.title}}</h4><p class="muted">修订 {{s.revision}} · {{s.readonly?'目录来源，只读':'项目内容'}}</p><blockquote>{{s.quote}}</blockquote><p v-if="s.stale" class="error">来源已变化或不可用：{{s.unavailable||'请重新分析'}}</p><details v-if="s.content"><summary>查看完整原文</summary><MarkdownView :content="s.content"/></details></article></div><p>{{selected.reason}}</p><form v-if="selected.status==='pending'" @submit.prevent="decide('merge')"><label>合并标题<input v-model="title" required maxlength="200" aria-label="治理合并标题"></label><label>合并稿<textarea v-model="content" required rows="12" :maxlength="kind==='memory'?10000:200000" aria-label="治理合并稿"></textarea></label><details><summary>阅读效果</summary><MarkdownView :content="content"/></details><p class="muted">默认新增合并稿并保留原记录；勾选下列来源将软删除该记录，原文仍保留在已移除内容中。</p><label v-for="s in selected.sources.filter((s:any)=>!s.readonly)" :key="s.id" class="check"><input type="checkbox" v-model="retired" :value="s.id" :disabled="kind==='memory'&&!confirmMemory">保存后移除「{{s.title}}」</label><label v-if="kind==='memory'" class="check"><input type="checkbox" v-model="confirmMemory" @change="retired=[]">合并后的记忆已经核实为事实（否则保存为待确认；保留来源中最早的过期时间）</label><label class="check governance-confirm"><input type="checkbox" v-model="reviewed">我已核对双方来源、合并稿及移除选择</label><div class="actions"><button class="primary" :disabled="busy||stale||!reviewed||!title.trim()||!content.trim()">确认保存合并稿</button><button type="button" @click="decide('keep_both')" :disabled="busy||stale||!reviewed">保留双方</button><button type="button" @click="decide('dismiss')" :disabled="busy||!reviewed">忽略建议</button></div></form><div v-else><p>此建议已处理：{{labels[selected.status]}}。</p><MarkdownView :content="selected.reviewed_content||selected.content"/></div></template><p v-else class="empty">选择一组建议，核对原文并决定如何处理。</p></div></div>
   <Pagination :page="page" :page-size="pageSize" :pages="pages" :total="total" label="治理建议" :busy="loading" @change="selected=null;action(()=>load($event),'')" @size="pageSize=$event;selected=null;action(()=>load(1),'')"/>
  </template>
 </section>
</template>
<style scoped>
.governance-panel{padding:24px;border:1px solid #dce3f3;border-radius:16px;background:#fff;margin:20px 0}.governance-controls{display:flex;align-items:end;gap:24px}.governance-controls label{max-width:260px}.governance-task{background:#f5f7ff;border-radius:12px;padding:16px;margin:18px 0}.governance-layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:24px;align-items:start}.governance-list{display:grid;gap:12px}.governance-card{padding:16px;text-align:left;white-space:normal;width:100%;border-radius:12px;background:#fafbff}.governance-card.chosen{border-color:#6355eb;background:#f0eeff}.governance-card p{line-height:1.6;font-weight:400;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.governance-badge{padding:4px 8px;border-radius:6px;font-size:12px}.duplicate{background:#ebe8ff;color:#5943b5}.conflict{background:#fff0dd;color:#96550d}.governance-reader{padding:20px;border:1px solid #e3e7f0;border-radius:12px;min-width:0}.governance-sources{display:grid;grid-template-columns:1fr 1fr;gap:12px}.governance-sources article{min-width:0;background:#f8f9fc;padding:16px;border-radius:10px}.governance-sources h4{margin:0}.governance-sources blockquote{margin:12px 0 0;padding:8px 12px;border-left:3px solid #b0a8eb;white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;line-height:1.7}.governance-confirm{background:#f5f3ff;padding:12px;border-radius:8px;margin:16px 0}.governance-reader textarea{resize:vertical}
</style>
