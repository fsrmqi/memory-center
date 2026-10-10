<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { action, api, states, type Item } from '../api'
import MarkdownView from './MarkdownView.vue'
const props=defineProps<{workspace:string;kind:'document'|'wiki'|'memory'}>()
const items=ref<Item[]>([]), title=ref(''), content=ref(''), query=ref(''), mode=ref('hybrid'), results=ref<any>(null), editing=ref<Item|null>(null), confirmed=ref(false), refs=ref<string[]>([]), busy=ref(false)
const selectedItem=ref<Item|null>(null), filter=ref(''), appliedFilter=ref(''), status=ref(''), page=ref(1), pageSize=ref(10), total=ref(0), pages=ref(1), loading=ref(false), formOpen=ref(false), dialog=ref<HTMLDialogElement|null>(null)
const organized=ref<any>(null), organizing=ref(false), organizeTitle=ref(''), organizeContent=ref('')
const captureEnabled=ref(false),captureSource=ref(''),captureContent=ref('')
async function bulkOrganize(){await action(async()=>{await api(`/workspaces/${props.workspace}/knowledge-tasks`,'POST',{kind:props.kind})},'已提交全库整理，请在后台任务的知识整理中审阅结果')}
async function captureSettings(){await action(async()=>{await api(`/workspaces/${props.workspace}/capture-settings`,'PUT',{enabled:captureEnabled.value})},'会话采集设置已保存')}
async function capture(){await action(async()=>{await api(`/workspaces/${props.workspace}/session-candidates`,'POST',{source_id:captureSource.value,content:captureContent.value});captureContent.value='';await load()},'会话资料已保存为待确认候选')}
const evaluationInput=ref(''),evaluationResult=ref<any>(null)
async function evaluateRetrieval(){await action(async()=>{evaluationResult.value=await api(`/workspaces/${props.workspace}/retrieval-evaluation`,'POST',{cases:JSON.parse(evaluationInput.value),limit:10})},'检索评测已完成')}
const labels={document:'知识库',wiki:'Wiki',memory:'长期记忆'}
let request=0
async function load(targetPage=page.value){
 if(!props.workspace)return
 const sequence=++request,workspace=props.workspace,kind=props.kind;loading.value=true
 try{if(kind==='memory'){const controls=await api(`/workspaces/${workspace}/capture-settings`);if(sequence!==request)return;captureEnabled.value=controls.enabled}
 const params=new URLSearchParams({page:String(targetPage),page_size:String(pageSize.value),q:appliedFilter.value,status:status.value});const data=await api(`/workspaces/${workspace}/knowledge/${kind}?${params}`)
 if(sequence!==request)return
 items.value=data.items;total.value=data.total;pages.value=data.pages;page.value=data.page
 if(selectedItem.value)selectedItem.value=items.value.find(i=>i.id===selectedItem.value?.id)||null
 }finally{if(sequence===request)loading.value=false}
}
watch(()=>[props.workspace,props.kind],()=>{request++;items.value=[];selectedItem.value=null;formOpen.value=false;results.value=null;evaluationResult.value=null;organized.value=null;filter.value='';appliedFilter.value='';status.value='';page.value=1;total.value=0;action(load,'')},{immediate:true})
async function applyFilter(){appliedFilter.value=filter.value;page.value=1;selectedItem.value=null;await action(load,'')}
async function turn(value:number){selectedItem.value=null;await action(()=>load(value),'')}
async function openEditor(item?:Item){editing.value=item||null;title.value=item?.title||'';content.value=item?.content||'';refs.value=[...(item?.refs||[])];confirmed.value=false;formOpen.value=true;await nextTick();dialog.value?.showModal()}
function closeEditor(){formOpen.value=false;editing.value=null}
async function save(){busy.value=true;await action(async()=>{const base=`/workspaces/${props.workspace}`; if(props.kind==='document')await api(base+'/documents','POST',{filename:title.value,content:content.value});if(props.kind==='wiki')await api(base+'/wiki'+(editing.value?'/'+editing.value.id:''),editing.value?'PATCH':'POST',{title:title.value,content:content.value,refs:refs.value,...(editing.value?{revision:editing.value.revision}:{})});if(props.kind==='memory')await api(base+'/memories','POST',{content:content.value,confirmed:confirmed.value});closeEditor();page.value=1;await load()},'已保存，重新索引后可检索');busy.value=false}
async function file(event:Event){const f=(event.target as HTMLInputElement).files?.[0];if(!f)return;if(f.size>4*1024*1024){await action(async()=>{throw new Error('文件不能超过 4 MiB')});return};busy.value=true;await action(async()=>{const data=new Uint8Array(await f.arrayBuffer());let raw='';for(const byte of data)raw+=String.fromCharCode(byte);await api(`/workspaces/${props.workspace}/documents`,'POST',{filename:f.name,content:btoa(raw),encoding:'base64'});page.value=1;await load()},'文档已导入，重新索引后可检索');busy.value=false;(event.target as HTMLInputElement).value=''}
async function state(item:Item,value:string){if(value==='deleted'&&!window.confirm(`移除“${item.title||'这条内容'}”？`))return;busy.value=true;await action(async()=>{await api(`/workspaces/${props.workspace}/knowledge/${props.kind}/${item.id}`,'PATCH',{revision:item.revision,status:value});await load()},value==='deleted'?'内容已移除':'状态已更新');busy.value=false}
async function search(){busy.value=true;await action(async()=>{results.value=await api(`/workspaces/${props.workspace}/search`,'POST',{query:query.value,mode:mode.value})},'检索完成');busy.value=false}
async function draft(){busy.value=true;await action(async()=>{const d=await api(`/workspaces/${props.workspace}/wiki-draft`,'POST',{title:query.value,query:query.value});await openEditor();content.value=d.content;title.value=d.title;refs.value=d.refs},'草稿已生成，请审阅后保存');busy.value=false}
async function rollback(item:Item,target:number){if(!window.confirm(`将“${item.title}”回滚至修订 ${target}？`))return;busy.value=true;await action(async()=>{await api(`/workspaces/${props.workspace}/wiki/${item.id}/rollback`,'POST',{revision:item.revision,target_revision:target});await load()},'已回滚为新修订');busy.value=false}
async function organize(batch=false){
 const ids=batch?items.value.filter(i=>!['deleted','rejected'].includes(i.status||'')).map(i=>i.id):selectedItem.value?[selectedItem.value.id]:[]
 if(!ids.length||organizing.value)return
 const workspace=props.workspace,kind=props.kind;organizing.value=true
 await action(async()=>{const result=await api(`/workspaces/${workspace}/organize`,'POST',{kind,record_ids:ids});if(workspace!==props.workspace||kind!==props.kind)return;organized.value=result;organizeTitle.value=result.title;organizeContent.value=result.content},'整理结果已生成，请审阅后保存')
 organizing.value=false
}
async function applyOrganized(){if(!organized.value)return;busy.value=true;const draft=organized.value
 await action(async()=>{await api(`/workspaces/${props.workspace}/organize/${draft.id}/apply`,'POST',{revision:draft.revision,title:organizeTitle.value,content:organizeContent.value});organized.value=null;await load()},'整理结果已保存；模型整理后的记忆需重新确认，重新索引后可检索')
 busy.value=false
}
async function refreshKnowledge(){await action(async()=>{await api(`/workspaces/${props.workspace}/knowledge-tasks`,'POST',{kind:'refresh'})},'知识刷新已排队，不重新解析源码')}
async function index(){busy.value=true;await action(async()=>{await api(`/workspaces/${props.workspace}/index`,'POST')},'索引任务已提交');busy.value=false}
</script>
<template>
 <section class="form-panel" v-if="kind==='memory'"><h2>受控会话资料</h2><label class="check"><input type="checkbox" v-model="captureEnabled" :disabled="!workspace" @change="captureSettings">允许向本项目提交会话资料</label><form v-if="captureEnabled" @submit.prevent="capture"><label>来源标识<input v-model="captureSource" required maxlength="200" placeholder="会话或资料的标识"></label><label>待提炼资料<textarea v-model="captureContent" required maxlength="10000" rows="4"></textarea></label><p class="muted">相同来源与内容不会重复保存；资料默认待确认，可通过全库整理提炼后审阅。</p><button>保存候选</button></form></section>
 <button v-if="kind!=='document'" @click="bulkOrganize" :disabled="!workspace||busy">后台整理全部 {{kind==='wiki'?'Wiki':'记忆'}} 内容</button>
 <div class="page-title"><div><div class="eyebrow">项目知识空间</div><h1>{{labels[kind]}}</h1><p>{{kind==='wiki'?'把项目经验整理为可阅读、可修订的知识页面。':'集中保存项目资料与经过确认的长期记忆。'}}</p></div><div class="actions"><button @click="refreshKnowledge" :disabled="!workspace||busy">刷新知识索引</button><button @click="index" :disabled="!workspace||busy">重新索引</button><button class="primary" @click="openEditor()" :disabled="!workspace||busy">＋ {{kind==='wiki'?'新建页面':'添加内容'}}</button></div></div>
 <p v-if="!workspace" class="empty">请先在项目管理中添加项目。</p>
 <template v-else>
  <section class="search-panel compact-search"><form class="toolbar" @submit.prevent="search"><span class="search-label">检索项目知识</span><input v-model="query" required placeholder="输入问题、关键词或代码符号" aria-label="检索内容"><select v-model="mode" aria-label="检索模式"><option value="hybrid">混合检索</option><option value="keyword">关键词</option><option value="vector">向量</option><option value="symbol">代码符号</option><option value="callers">调用方</option><option value="callees">被调用方</option></select><button class="primary" :disabled="busy">检索</button><button v-if="kind==='wiki'" type="button" @click="draft" :disabled="!query||busy">生成来源草稿</button></form>
   <div v-if="results" class="search-results"><div class="panel-heading"><h2>检索结果</h2><button @click="results=null">收起结果</button></div><p class="muted">{{results.state||'代码事实结果'}} · {{results.vector_enabled?'向量已启用':'关键词 / 代码检索'}} · 引用 {{results.ref_id}}</p><p v-if="results.reranking?.enabled" class="muted">{{results.reranking.state==='applied'?'模型重排已应用':'模型重排失败，已使用原排序'}}</p><p v-if="results.vector_reindex_required" class="muted">模型配置已变化，请重新索引。</p><article v-for="hit in results.items" :key="hit.chunk_id" class="hit"><h3>{{hit.source.path||hit.source.title}}</h3><p class="muted">来源标识 {{hit.source.source_id}}</p><p class="muted">行 {{hit.source.line}}–{{hit.source.end_line}} · {{hit.freshness==='STALE'?'来源已变化':'当前来源'}}</p><pre>{{hit.content}}</pre></article><pre v-if="!results.items">{{JSON.stringify(results,null,2)}}</pre><p v-if="results.items?.length===0" class="empty">当前范围没有命中；这不代表源码或资料中不存在。</p></div>
  </section>
  <details class="form-panel"><summary>检索评测</summary><p class="muted">提供已人工核对的查询与期望来源标识，回放真实检索结果；不会自动调参。</p><form @submit.prevent="evaluateRetrieval"><label>评测样例 JSON<textarea v-model="evaluationInput" required rows="5" placeholder='[{"query":"问题","expected_sources":["来源标识"],"mode":"hybrid"}]'></textarea></label><button>运行评测</button></form><div v-if="evaluationResult"><p>平均召回率 {{(evaluationResult.mean_recall*100).toFixed(1)}}% · 平均准确率 {{(evaluationResult.mean_precision*100).toFixed(1)}}%</p><pre>{{JSON.stringify(evaluationResult.cases,null,2)}}</pre></div></details>
  <section v-if="organized" class="form-panel">
    <div class="panel-heading"><div><h2>智能整理预览</h2><p class="muted">{{organized.copy?'将保存为新内容，保留来源。':'确认后保存为新修订，保留原文历史。'}} · 模型 {{organized.model}}</p></div><button @click="organized=null" :disabled="busy">放弃预览</button></div>
    <p class="muted">来源：{{organized.sources.map((s:any)=>s.title).join('、')}}。请检查事实、遗漏和冲突；预览有效期 30 分钟。</p>
    <label>标题<input v-model="organizeTitle" maxlength="200"></label><label>整理后的正文<textarea v-model="organizeContent" rows="14" :maxlength="kind==='memory'?10000:200000"></textarea></label>
    <details><summary>阅读效果</summary><MarkdownView :content="organizeContent"/></details>
    <button class="primary" @click="applyOrganized" :disabled="busy||!organizeTitle.trim()||!organizeContent.trim()">确认保存整理结果</button>
  </section>
  <p v-if="organizing" class="loading-text" role="status">模型正在整理选中的内容，原文仍然保留…</p>
  <div class="library-layout">
   <section class="library-list" :aria-busy="loading">
    <div class="panel-heading"><div><h2>已保存内容 <span class="count">{{total}}</span></h2><p class="muted">按最近更新排序</p></div><div class="actions"><button v-if="kind!=='document'" @click="organize(true)" :disabled="loading||busy||organizing||!items.length">整理当前页</button><button @click="action(load,'内容已刷新')" :disabled="loading">刷新</button></div></div>
    <form class="library-filter" @submit.prevent="applyFilter"><input v-model="filter" placeholder="筛选标题或路径" aria-label="筛选已保存内容"><select v-model="status" @change="applyFilter" aria-label="内容状态"><option value="">全部有效内容</option><option v-if="kind!=='memory'" value="active">使用中</option><template v-if="kind==='memory'"><option value="confirmed">已确认</option><option value="pending">待确认</option><option value="rejected">已拒绝</option></template><option value="deleted">已移除</option></select><button :disabled="loading">筛选</button></form>
    <p v-if="loading" class="loading-text" role="status">正在加载内容…</p>
    <div v-else class="entry-list"><button v-for="item in items" :key="item.id" class="library-entry" :class="{chosen:selectedItem?.id===item.id}" @click="selectedItem=item"><div class="entry-top"><span class="entry-icon">{{kind==='wiki'?'W':kind==='memory'?'M':'D'}}</span><span :class="['badge',item.status]">{{item.readonly?'目录来源':item.status==='active'?'使用中':states[item.status||'']||'使用中'}}</span></div><h3>{{item.title||'未命名内容'}}</h3><p class="entry-preview">{{(item.content||'').slice(0,180)}}</p><div class="entry-meta"><span>{{item.source_name||'项目内容'}}</span><span>{{item.updated_at?new Date(item.updated_at).toLocaleDateString():'修订 '+item.revision}}</span></div></button><div v-if="!items.length" class="empty"><span class="empty-mark">◇</span><h3>{{appliedFilter||status?'没有匹配的内容':'知识从这里开始'}}</h3><p>{{appliedFilter||status?'调整筛选条件后重试。':'添加文档、写下经验，或在 Wiki 目录接入已有资料。'}}</p></div></div>
    <div class="pagination" aria-label="内容分页"><label>每页<select v-model="pageSize" @change="turn(1)" :disabled="loading"><option :value="10">10 条</option><option :value="20">20 条</option><option :value="50">50 条</option></select></label><div class="pager-buttons"><button aria-label="上一页" @click="turn(page-1)" :disabled="page<=1||loading">‹</button><span>第 {{page}} / {{pages}} 页</span><button aria-label="下一页" @click="turn(page+1)" :disabled="page>=pages||loading">›</button></div></div>
   </section>
   <section class="reader-panel">
    <template v-if="selectedItem"><div class="reader-heading"><span class="eyebrow">{{selectedItem.source_name||'项目内容'}} · 修订 {{selectedItem.revision}}</span><h2>{{selectedItem.title}}</h2><div class="actions"><button v-if="kind!=='document'&&!['deleted','rejected'].includes(selectedItem.status||'')" @click="organize()" :disabled="busy||organizing">智能整理</button><button v-if="kind==='wiki'&&!selectedItem.readonly&&selectedItem.status!=='deleted'" @click="openEditor(selectedItem)" :disabled="busy">编辑页面</button><template v-if="kind==='memory'&&selectedItem.status==='pending'"><button @click="state(selectedItem,'confirmed')" :disabled="busy">确认事实</button><button @click="state(selectedItem,'rejected')" :disabled="busy">拒绝</button></template><button v-if="!selectedItem.readonly&&selectedItem.status!=='deleted'" class="danger" @click="state(selectedItem,'deleted')" :disabled="busy">删除</button></div><p v-if="selectedItem.readonly" class="source-note">{{selectedItem.relative_path}} · 只读来源，请在原文件修改后同步。</p></div><MarkdownView :content="selectedItem.content||''"/><details v-if="kind==='wiki'&&selectedItem.versions?.length" class="version-history"><summary>历史版本 · {{selectedItem.versions.length}} 次修订</summary><p v-for="v in selectedItem.versions" :key="v.revision">修订 {{v.revision}} <button @click="rollback(selectedItem,v.revision)" :disabled="busy">回滚至此版本</button></p></details></template>
    <div v-else class="reader-empty"><div class="reader-symbol">▤</div><h2>选择一篇内容，开始阅读</h2><p>在左侧浏览已保存内容。<br>页面正文、来源和历史修订将在这里展示。</p><button @click="openEditor()" class="primary">{{kind==='wiki'?'新建 Wiki 页面':'添加第一条内容'}}</button></div>
   </section>
  </div>
  <label v-if="kind==='document'" class="upload file-import">导入文档<input type="file" accept=".txt,.md,.pdf,.docx,.rst,.csv,.json,.yaml,.yml" @change="file" :disabled="busy"><small>支持文本、Markdown、PDF、DOCX，最多 4 MiB；扫描 PDF 需先 OCR。</small></label>
 </template>
 <dialog v-if="formOpen" ref="dialog" class="editor-dialog" @cancel.prevent="closeEditor"><form @submit.prevent="save"><div class="panel-heading"><div><div class="eyebrow">{{labels[kind]}}</div><h2>{{editing?'修订页面':'添加内容'}}</h2></div><button type="button" @click="closeEditor" aria-label="关闭编辑器">✕</button></div><label v-if="kind!=='memory'">{{kind==='document'?'文档名称':'页面标题'}}<input v-model="title" required maxlength="200" autofocus placeholder="一个清晰、易查找的标题"></label><label>内容<textarea v-model="content" required rows="14" :maxlength="kind==='memory'?10000:200000" placeholder="记录内容，支持 Markdown 格式"></textarea></label><label v-if="kind==='memory'" class="check"><input type="checkbox" v-model="confirmed">这是已经明确确认的事实</label><p class="muted">{{kind==='memory'?'推断默认进入待确认状态；只有确认的记忆进入检索。':'保存后重新索引，内容即可进入项目检索。'}}</p><div class="dialog-actions"><button type="button" @click="closeEditor">取消</button><button class="primary" :disabled="busy">{{busy?'正在保存…':editing?'保存修订':'保存内容'}}</button></div></form></dialog>
</template>
