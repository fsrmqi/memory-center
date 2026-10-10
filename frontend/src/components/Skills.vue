<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, action } from '../api'
import Pagination from './Pagination.vue'
import SkillDiscovery from './SkillDiscovery.vue'
import { usePagination } from '../pagination'
const tab=ref('discovery')
const candidates = ref<any[]>([])
const published = ref<any[]>([])
const filter=ref(''),candidatePager=usePagination(()=>candidates.value.filter(i=>i.name.toLowerCase().includes(filter.value.toLowerCase()))),publishedPager=usePagination(()=>published.value.filter(i=>i.name.toLowerCase().includes(filter.value.toLowerCase())))
watch(filter,()=>{candidatePager.reset();publishedPager.reset()})
const name = ref('')
const description = ref('')
const body = ref('')
const paths = ref('')
const evidence = ref('')
const result = ref<any>(null)
const pending = ref<any>(null)
const viewed = ref<any>(null)
const busy = ref(false)
const creating = ref(false)
async function operation(p: any) { return api('/governance/assistant_skill', 'POST', { parameters: p }) }
async function load() {
  candidates.value = (await operation({ action: 'list' })).candidates
  published.value = (await operation({ action: 'published' })).items
}
async function run(p: any) {
  busy.value = true
  await action(async () => {
    result.value = await operation(p)
    pending.value = ['create', 'publish', 'remove'].includes(p.action) && !p.confirm ? p : null
    await load()
  }, '处理完成')
  busy.value = false
}
function sourcePaths() { return paths.value.split('\n').map(s => s.trim()).filter(Boolean) }
function evidenceRefs() { return evidence.value.split('\n').map(s => s.trim()).filter(Boolean) }
async function create() {
  await run({ action: 'create', name: name.value, description: description.value, body: body.value, source_paths: sourcePaths() })
}
async function publish(item: any) {
  await run({ action: 'publish', name: item.name, evidence_refs: evidenceRefs() })
}
async function download(item: any) {
  await action(async () => {
    const value = await operation({ action: 'export', name: item.name })
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = item.name + '.json'; a.click(); URL.revokeObjectURL(url)
  }, 'Skill 已导出')
}
async function view(item: any, isPublished: boolean) {
  busy.value = true
  await action(async () => { viewed.value = await operation({ action: 'read', name: item.name, published: isPublished }) }, 'Skill 内容已加载')
  busy.value = false
}
watch(tab,()=>{viewed.value=null;result.value=null;pending.value=null})
onMounted(() => action(load, ''))
</script>
<template>
  <div class="page-title">
    <div><h1>Skill 管理</h1><p>资料提取、候选审阅、完整性校验与发布；发布需要任务验证引用。</p></div>
    <button class="primary" @click="tab='candidates';creating=!creating">{{creating?'收起':'创建候选'}}</button>
  </div>
  <div class="tabs" role="tablist" aria-label="Skill 分组"><button v-for="t in [{id:'discovery',label:'全局发现'},{id:'candidates',label:'候选 Skill'},{id:'published',label:'已发布 Skill'}]" :key="t.id" role="tab" :aria-selected="tab===t.id" :class="{current:tab===t.id}" @click="tab=t.id">{{t.label}}</button></div>
  <SkillDiscovery v-show="tab==='discovery'"/>
  <div v-if="tab!=='discovery'" class="toolbar"><input v-model="filter" placeholder="筛选候选及已发布 Skill" aria-label="筛选受管 Skill"></div>
  <form v-if="creating&&tab==='candidates'" class="form-panel skill-panel" @submit.prevent="create">
    <label>名称<input v-model="name" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" required placeholder="例如 project-review"></label>
    <label>适用场景<input v-model="description" required></label>
    <label>来源文件或目录（每行一个）<textarea v-model="paths" required placeholder="已登记项目、Wiki 或受管知识目录的路径"></textarea></label>
    <div class="actions">
      <button type="button" :disabled="busy" @click="run({action:'analyze',source_paths:sourcePaths()})">分析来源</button>
      <button type="button" :disabled="busy" @click="run({action:'extract',source_paths:sourcePaths()})">提取资料</button>
    </div>
    <label>Skill 正文<textarea v-model="body" rows="10" required placeholder="操作方法、决策规则、验证步骤与适用边界"></textarea></label>
    <button class="primary" :disabled="busy">生成候选预览</button>
  </form>
  <section v-show="tab==='candidates'" class="form-panel skill-panel">
    <h2>候选 Skill</h2>
    <p v-if="!candidates.length" class="muted">暂无候选。先分析来源资料，再编写 Skill 内容。</p>
    <label>发布验证引用（每行一个）<textarea v-model="evidence" placeholder="Memory Center 任务、引用或验证记录"></textarea></label>
    <table v-if="candidates.length">
      <thead><tr><th>名称</th><th>来源数</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="item in candidatePager.rows.value" :key="item.name">
          <td>{{item.name}}</td>
          <td>{{item.source_count}}</td>
          <td class="actions">
            <button @click="run({action:'inspect',name:item.name})">审阅</button>
            <button @click="run({action:'validate',name:item.name})">校验</button>
            <button :disabled="busy" @click="view(item,false)">查看</button>
            <button @click="publish(item)">发布预览</button>
            <button @click="download(item)">导出</button>
            <button @click="run({action:'remove',name:item.name})">移除</button>
          </td>
        </tr>
      </tbody>
    </table>
    <Pagination :page="candidatePager.page.value" :page-size="candidatePager.pageSize.value" :total="candidatePager.total.value" :pages="candidatePager.pages.value" label="候选 Skill" @change="candidatePager.page.value=$event" @size="candidatePager.pageSize.value=$event;candidatePager.reset()"/>
  </section>
  <section v-show="tab==='published'" class="form-panel skill-panel">
    <h2>已发布 Skill</h2>
    <p class="muted">只展示本服务发布的 Skill。已有全局 Skill 请使用上方发现功能登记并启用。</p>
    <p v-if="!published.length">暂无受管发布的 Skill。</p>
    <table v-else>
      <thead><tr><th>名称</th><th>来源</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="item in publishedPager.rows.value" :key="item.name">
          <td>{{item.name}}</td>
          <td>{{item.publication?'受管发布':'已有 Skill'}}</td>
          <td class="actions">
            <button :disabled="busy" @click="view(item,true)">查看</button>
            <button @click="run({action:'remove',name:item.name,published:true})">停用</button>
          </td>
        </tr>
      </tbody>
    </table>
    <Pagination :page="publishedPager.page.value" :page-size="publishedPager.pageSize.value" :total="publishedPager.total.value" :pages="publishedPager.pages.value" label="已发布 Skill" @change="publishedPager.page.value=$event" @size="publishedPager.pageSize.value=$event;publishedPager.reset()"/>
  </section>
  <section v-if="viewed" class="form-panel skill-panel">
    <h2>{{viewed.name}}<span class="muted"> · {{viewed.published?'已启用':'候选'}}</span></h2>
    <p class="muted">文件：{{Object.keys(viewed.files).join('、')}}</p>
    <pre class="result-text">{{viewed.body}}</pre>
    <div class="actions"><button @click="viewed=null">关闭</button></div>
  </section>
  <section v-if="result" class="form-panel skill-panel">
    <h2>审阅结果</h2>
    <pre class="result-text">{{JSON.stringify(result,null,2)}}</pre>
    <button v-if="pending" class="primary" :disabled="busy" @click="run({...pending,confirm:true})">确认{{pending.action==='publish'?'发布':pending.action==='remove'?'移除':'创建'}}</button>
  </section>
</template>
