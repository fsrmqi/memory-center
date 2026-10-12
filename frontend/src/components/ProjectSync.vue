<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {api,action} from '../api'
const emit=defineEmits<{checked:[]}>()
const props=defineProps<{workspace:string}>()
const settings=ref<any>(null),state=ref<any>(null),busy=ref(false),loading=ref(false)
const labels:Record<string,string>={config_changed:'项目配置需更新',unchecked:'尚未检查',current:'索引最新',changed:'源码已变化',not_indexed:'待建立索引',baseline_required:'待更新增量基线',error:'检查失败',waiting_capacity:'等待队列空位',pending:'索引已排队或运行',blocked:'自动调度已停止',disabled:'自动同步已关闭',watching:'等待源码变化'}
let sequence=0,timer:ReturnType<typeof setInterval>
async function load(){const seq=++sequence,w=props.workspace;loading.value=true;try{const [a,b]=await Promise.all([api(`/workspaces/${w}/sync-settings`),api(`/workspaces/${w}/sync-status`)]);if(seq!==sequence)return;settings.value=a;state.value=b;emit('checked')}finally{if(seq===sequence)loading.value=false}}
async function save(){busy.value=true;await action(async()=>{settings.value=await api(`/workspaces/${props.workspace}/sync-settings`,'PUT',{enabled:settings.value.enabled,interval_seconds:settings.value.interval_seconds,debounce_seconds:settings.value.debounce_seconds,revision:settings.value.revision});await load()},'自动同步设置已保存');busy.value=false}
async function check(){if(busy.value)return;busy.value=true;const w=props.workspace;await action(async()=>{const result=await api(`/workspaces/${w}/sync-check`,'POST');if(w===props.workspace){state.value=result;emit('checked')}},'源码检查完成');busy.value=false}
function date(value:string){return value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'尚无记录'}
watch(()=>props.workspace,()=>{sequence++;settings.value=null;state.value=null;action(load,'')},{immediate:true})
onMounted(()=>{timer=setInterval(async()=>{if(busy.value||loading.value||!props.workspace)return;try{const w=props.workspace,data=await api(`/workspaces/${w}/sync-status`);if(w===props.workspace)state.value=data}catch{}},5000)})
onUnmounted(()=>{sequence++;clearInterval(timer)})
</script>
<template>
<section class="sync-panel" v-if="settings"><div class="panel-heading"><div><h2>源码同步与索引状态</h2><p>开启后检测源码变化，等待修改稳定后自动提交增量索引。</p></div><button @click="check" :disabled="busy">{{busy?'处理中…':'检查源码变化'}}</button></div>
<div class="sync-status" v-if="state"><strong>{{labels[state.state]||state.state}}</strong><span>{{labels[state.schedule_state]||state.schedule_state}}</span><span v-if="state.changed_files!==null&&state.changed_files!==undefined">变化 {{state.changed_files}} 文件</span><span>上次成功：{{date(state.last_success_at)}}</span><span>上次检查：{{date(state.checked_at)}}</span></div>
<p v-if="state?.error||state?.schedule_state==='blocked'" class="error">{{state.error||'上次索引失败、取消或中断；处理原因后手动索引成功，才会恢复自动调度。'}}</p>
<form class="sync-controls" @submit.prevent="save"><label class="check"><input v-model="settings.enabled" type="checkbox" aria-label="启用项目自动同步" :disabled="busy">启用自动同步</label><label>检查间隔（秒）<input v-model.number="settings.interval_seconds" type="number" min="10" max="86400" required :disabled="busy"></label><label>修改稳定等待（秒）<input v-model.number="settings.debounce_seconds" type="number" min="1" max="3600" required :disabled="busy"></label><button class="primary" :disabled="busy">保存同步设置</button></form>
<p class="muted">默认关闭。失败不会自动重试；暂停项目会停止自动调度。关闭同步只停止后续调度，已提交的任务可在后台任务中取消。旧索引首次重建后建立增量基线。</p></section>
</template>
<style scoped>.sync-panel{background:#fff;border:1px solid #dce3f3;border-radius:16px;padding:24px;margin:20px 0}.sync-status{display:flex;flex-wrap:wrap;gap:12px 24px;padding:16px;background:#f5f7ff;border-radius:10px}.sync-status span{color:#667085;font-size:13px}.sync-controls{display:flex;gap:20px;align-items:end;margin:20px 0}.sync-controls label:not(.check){width:200px}.sync-controls .check{align-self:center;margin:0}.sync-controls button{white-space:nowrap}</style>
