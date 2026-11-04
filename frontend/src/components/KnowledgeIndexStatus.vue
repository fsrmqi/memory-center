<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {api,action} from '../api'
import Pagination from './Pagination.vue'
const emit=defineEmits<{submitted:[task:any]}>()
const props=defineProps<{workspace:string;kind:string;refreshKey?:number}>()
const data=ref<any>(null),busy=ref(false),loading=ref(false),opened=ref(false),page=ref(1)
const reasons:Record<string,string>={added:'尚未进入索引',updated:'修订尚未刷新',removed:'旧索引待清理',source_changed:'原 Wiki 文件待同步'}
let sequence=0,timer:ReturnType<typeof setInterval>
async function load(target=page.value){const seq=++sequence,w=props.workspace,k=props.kind;loading.value=true;try{const result=await api(`/workspaces/${w}/knowledge-index-status?kind=${k}&page=${target}&page_size=10`);if(seq===sequence){data.value=result;page.value=result.page;if(!result.total)opened.value=false}}finally{if(seq===sequence)loading.value=false}}
async function refresh(){if(busy.value)return;busy.value=true;await action(async()=>{const task=await api(`/workspaces/${props.workspace}/knowledge-tasks`,'POST',{kind:'refresh'});emit('submitted',task);await load()},'知识刷新已排队；源码索引保留');busy.value=false}
watch(()=>[props.workspace,props.kind,props.refreshKey],()=>{sequence++;data.value=null;action(()=>load(1),'')},{immediate:true})
onMounted(()=>{timer=setInterval(async()=>{if(data.value?.refresh_task&&!busy.value&&!loading.value)try{await load()}catch{}},3000)})
onUnmounted(()=>{sequence++;clearInterval(timer)})
</script>
<template><section v-if="data" class="knowledge-index-status"><div class="panel-heading"><div><strong>{{data.state==='not_indexed'?'尚未建立项目索引':data.state==='changed'?`${data.total} 条来源等待知识刷新`:'知识索引已同步'}}</strong><p class="muted">{{data.refresh_task?'知识刷新正在排队或运行。':'保存内容与检索索引分别维护，刷新知识不会重新解析源码。'}}<span v-if="data.awaiting_confirmation"> {{data.awaiting_confirmation}} 条记忆待确认，确认后才能进入检索。</span></p></div><div class="actions"><button @click="action(()=>load(),'')" :disabled="loading">检查知识状态</button><button v-if="data.total" @click="opened=!opened">{{opened?'收起来源':'查看待刷新来源'}}</button><button class="primary" @click="refresh" :disabled="busy||!!data.refresh_task||data.state==='not_indexed'||!!data.needs_source_sync">刷新知识索引</button></div></div><p v-if="data.needs_source_sync" class="error">原 Wiki 文件已变化，请先在 Wiki 目录页面同步来源，再刷新知识索引。</p><p v-if="data.state==='not_indexed'" class="muted">请先在项目管理建立源码索引，再刷新知识。</p><div v-if="opened"><table><thead><tr><th>来源</th><th>状态</th></tr></thead><tbody><tr v-for="row in data.items" :key="row.id"><td>{{row.title||row.id}}</td><td>{{reasons[row.reason]}}</td></tr></tbody></table><Pagination :page="data.page" :page-size="10" :total="data.total" :pages="data.pages" label="待刷新来源" :busy="loading" @change="action(()=>load($event),'')"/></div></section></template>
<style scoped>.knowledge-index-status{padding:20px 24px;background:#f5f7ff;border:1px solid #dce3f3;border-radius:14px;margin:16px 0}.knowledge-index-status .panel-heading{gap:24px}.knowledge-index-status p{margin:8px 0 0}.knowledge-index-status button{white-space:nowrap}.knowledge-index-status table{margin-top:16px}</style>
