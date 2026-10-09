<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, action, states, type Item } from '../api'
const items=ref<Item[]>([])
async function refresh(){await action(async()=>{items.value=(await api('/jobs')).items},'任务状态已更新')}
async function operation(item:Item,op:string){await action(async()=>{await api(`/jobs/${item.id}/${op}`,'POST');items.value=(await api('/jobs')).items})}
let timer:ReturnType<typeof setInterval>
onMounted(()=>{refresh();timer=setInterval(async()=>{try{items.value=(await api('/jobs')).items}catch{}},3000)})
onUnmounted(()=>clearInterval(timer))
</script>
<template><div class="page-title"><div><h1>后台任务</h1><p>最多两个索引进程并行，取消和失败保留上一代可用索引。</p></div><button @click="refresh">刷新</button></div><div class="table-wrap"><table><thead><tr><th>任务</th><th>项目</th><th>状态</th><th>进度</th><th>操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td class="mono">{{item.id}}<small class="error" v-if="item.error">{{item.error}} {{item.message}}</small></td><td class="mono">{{item.workspace_id}}</td><td><span class="state">{{states[item.status||'']}}</span></td><td><progress max="100" :value="item.progress"></progress> {{item.progress}}%</td><td><button v-if="['queued','running'].includes(item.status||'')" @click="operation(item,'cancel')">取消</button><button v-if="['failed','cancelled','interrupted'].includes(item.status||'')" @click="operation(item,'retry')">重试</button></td></tr></tbody></table></div><p v-if="!items.length" class="empty">没有后台任务。在项目页面启动索引。</p></template>
