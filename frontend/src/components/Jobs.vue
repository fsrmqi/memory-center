<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, action, failure, notice, states, type Item } from '../api'
import Pagination from './Pagination.vue'
const page=ref(1),pageSize=ref(10),pages=ref(1),total=ref(0),filter=ref(''),status=ref(''),appliedFilter=ref(''),appliedStatus=ref(''),loading=ref(false)
let sequence=0
async function load(target=page.value){const request=++sequence;loading.value=true;try{const data=await api('/jobs?'+new URLSearchParams({page:String(target),page_size:String(pageSize.value),q:appliedFilter.value,status:appliedStatus.value}));if(request!==sequence)return;items.value=data.items;page.value=data.page;pages.value=data.pages;total.value=data.total}finally{if(request===sequence)loading.value=false}}
async function applyFilter(){appliedFilter.value=filter.value;appliedStatus.value=status.value;await action(()=>load(1),'')}
const items = ref<Item[]>([])
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
    <div><h1>后台任务</h1><p>最多两个索引进程并行，取消和失败保留上一代可用索引。</p></div>
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
          <td><progress max="100" :value="item.progress"></progress> {{item.progress}}%</td>
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
