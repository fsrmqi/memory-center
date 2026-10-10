<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, action, failure, notice, states, type Item } from '../api'
import Pagination from './Pagination.vue'
const page=ref(1),pageSize=ref(10),pages=ref(1),total=ref(0),filter=ref(''),status=ref(''),appliedFilter=ref(''),appliedStatus=ref(''),loading=ref(false)
let sequence=0
async function load(target=page.value){const request=++sequence;loading.value=true;try{const data=await api('/jobs?'+new URLSearchParams({page:String(target),page_size:String(pageSize.value),q:appliedFilter.value,status:appliedStatus.value}));if(request!==sequence)return;items.value=data.items;page.value=data.page;pages.value=data.pages;total.value=data.total}finally{if(request===sequence)loading.value=false}}
async function applyFilter(){appliedFilter.value=filter.value;appliedStatus.value=status.value;await action(()=>load(1),'')}
const items = ref<Item[]>([])
const phases:Record<string,string>={queued:'等待调度',scanning:'扫描源码',chunking:'源码分块',parsing:'解析代码',relations:'解析调用关系',services:'服务专用分析',knowledge:'读取知识',embedding:'向量化',publishing:'发布索引'}
const units:Record<string,string>={files:'文件',services:'服务',chunks:'分块',items:'条目'}
async function refresh() {
  await action(async () => { await load() }, '任务状态已更新')
}
async function operation(item: Item, op: string) {
  await action(async () => {
    await api(`/jobs/${item.id}/${op}`, 'POST')
    await load()
  })
}
async function remove(item: Item) {
  await action(async () => {
    await api(`/jobs/${item.id}`, 'DELETE')
    await load()
  }, '任务已删除；若其索引已过期，可用“清理旧索引”回收空间')
}
async function prune() {
  let message = '旧索引已清理'
  await action(async () => {
    const result = await api('/jobs/prune', 'POST')
    await load()
    message = `已清理 ${result.removed} 个旧索引目录，释放 ${(result.freed_bytes / 1048576).toFixed(1)} MiB`
  })
  // action() 的固定消息在调用时求值，这里在任务完成后回填含释放空间的消息。
  if (!failure.value) notice.value = message
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
      <button @click="prune">清理旧索引</button>
    </div>
  </div>
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
          <td><span class="state">{{states[item.status||'']}}</span></td>
          <td><template v-if="item.status==='succeeded'">已完成 · 100%</template><template v-else-if="item.progress_scope==='phase'"><strong>{{phases[item.phase]||item.phase}}</strong><div><progress v-if="item.total" max="100" :value="item.progress"></progress><progress v-else-if="item.status==='running'" max="100"></progress> {{item.total ? `${item.completed} / ${item.total} ${units[item.unit]||''} · 阶段 ${item.progress}%` : `${item.completed||0} ${units[item.unit]||''} · 总量待确定`}}</div><small>{{item.detail}}</small><small v-if="item.started_at">已用时 {{Math.max(0,Math.round((Date.parse(item.finished_at||new Date().toISOString())-Date.parse(item.started_at))/1000))}} 秒</small></template><template v-else>旧任务阶段记录 · {{item.progress}}%</template></td>
          <td class="actions">
            <button v-if="['queued','running'].includes(item.status||'')" @click="operation(item,'cancel')">取消</button>
            <button v-if="['failed','cancelled','interrupted'].includes(item.status||'')" @click="operation(item,'retry')">重试</button>
            <button v-if="['failed','cancelled','interrupted','succeeded'].includes(item.status||'')" class="danger" @click="remove(item)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <Pagination :page="page" :page-size="pageSize" :total="total" :pages="pages" label="后台任务" :busy="loading" @change="action(()=>load($event),'')" @size="pageSize=$event;action(()=>load(1),'')"/>
  <p v-if="!items.length" class="empty">没有后台任务。在项目页面启动索引。</p>
</template>
