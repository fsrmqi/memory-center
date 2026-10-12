<script setup lang="ts">
import {onUnmounted,ref,watch} from 'vue'
import {api,states} from '../api'
import {navigateTo} from '../navigation'
const props=defineProps<{task:any;type:'index'|'knowledge'}>()
const current=ref<any>(props.task),error=ref('');let sequence=0
async function update(){const seq=++sequence;try{const value=props.type==='knowledge'?await api('/knowledge-tasks/'+props.task.id):(await api('/jobs?q='+encodeURIComponent(props.task.id)+'&page_size=10')).items.find((i:any)=>i.id===props.task.id);if(seq===sequence){if(value)current.value=value;error.value=value?'':'任务记录已不存在'}}catch{if(seq===sequence)error.value='暂时无法更新进度，可打开后台任务查看'}}
watch(()=>props.task,()=>{sequence++;current.value=props.task;error.value='';void update()})
const timer=setInterval(()=>{if(['queued','running'].includes(current.value.status))void update()},3000)
onUnmounted(()=>{sequence++;clearInterval(timer)})
</script>
<template><section class="submitted-task" role="status"><div><strong>{{type==='index'?'源码索引':current.kind==='refresh'?'知识刷新':'知识整理'}} · {{states[current.status]||current.status}}</strong><p>{{error||current.message||current.detail||(current.status==='succeeded'?'处理已完成，可查看结果。':'任务在后台运行，可以离开本页。')}}</p></div><button @click="navigateTo('jobs',{type,task:current.id,workspace:current.workspace_id})">{{current.status==='succeeded'?'查看结果':'查看进度'}}</button></section></template>
<style scoped>.submitted-task{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:16px 20px;margin:12px 0;background:#eef4ff;border:1px solid #cbdcff;border-radius:12px}.submitted-task p{margin:6px 0 0;color:#58677e}.submitted-task button{white-space:nowrap}</style>
