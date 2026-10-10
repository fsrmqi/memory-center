<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, action, failure, notice, states, type Item } from '../api'
const items = ref<Item[]>([])
async function refresh() {
  await action(async () => { items.value = (await api('/jobs')).items }, '任务状态已更新')
}
async function operation(item: Item, op: string) {
  await action(async () => {
    await api(`/jobs/${item.id}/${op}`, 'POST')
    items.value = (await api('/jobs')).items
  })
}
async function remove(item: Item) {
  await action(async () => {
    await api(`/jobs/${item.id}`, 'DELETE')
    items.value = (await api('/jobs')).items
  }, '任务已删除；若其索引已过期，可用“清理旧索引”回收空间')
}
async function prune() {
  let message = '旧索引已清理'
  await action(async () => {
    const result = await api('/jobs/prune', 'POST')
    items.value = (await api('/jobs')).items
    message = `已清理 ${result.removed} 个旧索引目录，释放 ${(result.freed_bytes / 1048576).toFixed(1)} MiB`
  })
  // action() 的固定消息在调用时求值，这里在任务完成后回填含释放空间的消息。
  if (!failure.value) notice.value = message
}
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  refresh()
  timer = setInterval(async () => {
    try { items.value = (await api('/jobs')).items } catch { /* 轮询失败不打断页面 */ }
  }, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>
<template>
  <div class="page-title">
    <div><h1>后台任务</h1><p>最多两个索引进程并行，取消和失败保留上一代可用索引。</p></div>
    <div class="actions">
      <button @click="refresh">刷新</button>
      <button @click="prune">清理旧索引</button>
    </div>
  </div>
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
  <p v-if="!items.length" class="empty">没有后台任务。在项目页面启动索引。</p>
</template>
