<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, action, type Item, type Workspace } from '../api'
import Pagination from './Pagination.vue'
import { usePagination } from '../pagination'
defineProps<{workspaces:Workspace[]}>()
const items=ref<Item[]>([]),editing=ref<Item|null>(null),busy=ref(false)
const name=ref(''),root=ref(''),workspaceIds=ref<string[]>([]),autoSync=ref(true),status=ref('active')
const filter=ref(''),pager=usePagination(()=>items.value.filter(i=>(i.name+i.root).toLowerCase().includes(filter.value.toLowerCase())))
watch(filter,pager.reset)
async function load(){items.value=(await api('/wiki-sources')).items}
function edit(item:Item){editing.value=item;name.value=item.name;root.value=item.root;workspaceIds.value=[...item.workspace_ids];autoSync.value=item.auto_sync;status.value=item.status||'active'}
function reset(){editing.value=null;name.value='';root.value='';workspaceIds.value=[];autoSync.value=true;status.value='active'}
async function save(){busy.value=true;await action(async()=>{await api('/wiki-sources'+(editing.value?'/'+editing.value.id:''),editing.value?'PATCH':'POST',{name:name.value,root:root.value,workspace_ids:workspaceIds.value,auto_sync:autoSync.value,status:status.value,...(editing.value?{revision:editing.value.revision}:{})});reset();await load()},'来源已保存；可立即同步，自动同步约每分钟检查一次');busy.value=false}
async function sync(item:Item){busy.value=true;await action(async()=>{try{await api('/wiki-sources/'+item.id+'/sync','POST')}finally{await load()}},'同步完成，可在后台任务中查看关联项目索引');busy.value=false}
async function remove(item:Item){busy.value=true;await action(async()=>{await api('/wiki-sources/'+item.id,'DELETE');await load();if(editing.value?.id===item.id)reset()},'来源已移除，原文件保持不变');busy.value=false}
onMounted(()=>action(load,'Wiki 来源已加载'))
</script>
<template>
  <div class="page-title"><div><h1>Wiki 目录</h1><p>接入多个本地 Markdown 目录，按需共享给项目；原文件只读。</p></div><button @click="action(load,'来源状态已刷新')" :disabled="busy">刷新状态</button></div>
  <div class="knowledge-columns">
    <section><h2>已接入目录</h2><input v-model="filter" aria-label="筛选 Wiki 目录" placeholder="搜索目录名称或路径"><article v-for="item in pager.rows.value" :key="item.id" class="entry">
      <h3>{{item.name}}</h3><span class="state">{{item.status==='active'?'已启用':'已暂停'}}</span>
      <p><code>{{item.root}}</code></p><p class="muted">{{item.page_count}} 页 · {{item.auto_sync?'每分钟自动检查':'手动同步'}} · {{item.sync_state==='ready'?'同步完成':item.sync_state==='failed'?'同步失败，保留上次结果':'待同步'}}</p>
      <p>关联项目：{{item.workspace_ids.map((id:string)=>workspaces.find(w=>w.workspace_id===id)?.name||'已移除项目').join('、')||'未关联，可先同步目录'}}</p>
      <p v-if="item.last_sync" class="muted">上次成功：{{new Date(item.last_sync).toLocaleString()}}</p>
      <p v-if="item.last_result" class="muted">新增 {{item.last_result.added}} · 更新 {{item.last_result.updated}} · 删除 {{item.last_result.deleted}} · 未变 {{item.last_result.unchanged}}</p>
      <p v-if="item.error" role="alert">{{item.error}}：请检查目录挂载、权限和 UTF-8 编码。</p>
      <div class="actions"><button @click="sync(item)" :disabled="busy||item.status!=='active'">立即同步</button><button @click="edit(item)" :disabled="busy">配置</button><button class="danger" @click="remove(item)" :disabled="busy">移除来源</button></div>
    </article><p v-if="!items.length" class="empty">尚未接入 Wiki 目录。添加目录后，可关联一个或多个项目。</p><Pagination :page="pager.page.value" :page-size="pager.pageSize.value" :total="pager.total.value" :pages="pager.pages.value" label="Wiki 目录" @change="pager.page.value=$event" @size="pager.pageSize.value=$event;pager.reset()"/></section>
    <section><h2>{{editing?'配置来源':'添加 Wiki 目录'}}</h2><form @submit.prevent="save">
      <label>来源名称<input v-model="name" required maxlength="120" placeholder="例如：技术规范"></label>
      <label>目录绝对路径<input v-model="root" required :readonly="!!editing" placeholder="/wiki/engineering"></label>
      <p class="muted">原生运行填写本机目录；OrbStack / Docker 填写挂载后的容器路径。递归读取 .md 和 .markdown，跳过隐藏目录和符号链接。</p>
      <label>来源状态<select v-model="status"><option value="active">启用</option><option value="paused">暂停</option></select></label>
      <fieldset><legend>关联项目（可多选）</legend><label v-for="workspace in workspaces" :key="workspace.workspace_id" class="check"><input type="checkbox" v-model="workspaceIds" :value="workspace.workspace_id">{{workspace.name}}</label><p v-if="!workspaces.length" class="muted">可先登记目录，再添加项目并配置关联。</p></fieldset>
      <label class="check"><input type="checkbox" v-model="autoSync">自动同步文件变化并更新关联项目索引</label>
      <p class="muted">每目录最多 2000 页 / 32 MiB，单页最多 1 MiB。读取失败不会将上次内容当作已删除。</p>
      <div class="actions"><button class="primary" :disabled="busy">保存来源</button><button v-if="editing" type="button" @click="reset" :disabled="busy">取消</button></div>
    </form></section>
  </div>
</template>
