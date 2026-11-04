<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'
import Pagination from './Pagination.vue'
import { usePagination } from '../pagination'

const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ cleaned: [] }>()
const keepHistory = ref(2), revision = ref(0), busy = ref(false), policyReady = ref(false)
const savedKeepHistory = ref(2)
const policyDirty = computed(() => keepHistory.value !== savedKeepHistory.value)
const parseCache = ref(false), embeddingCache = ref(false), preview = ref<any>(null)
const error = ref(''), message = ref('')
const pager = usePagination<{ path: string; files: number; bytes: number }>(() => preview.value?.candidates || [])
let sequence = 0
function size(value: number) {
  if (value < 1024) return `${value} B`
  const scale = value < 1048576 ? 1024 : 1048576
  return `${(value / scale).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${scale === 1024 ? 'KiB' : 'MiB'}`
}
async function load() {
  const seq = ++sequence
  preview.value = null; error.value = ''; message.value = ''; policyReady.value = false
  parseCache.value = false; embeddingCache.value = false; busy.value = true
  try {
    const data = await api(`/workspaces/${props.workspaceId}/storage-policy`)
    if (seq === sequence) { keepHistory.value = data.keep_history; savedKeepHistory.value = data.keep_history; revision.value = data.revision; policyReady.value = true }
  } catch (cause) { if (seq === sequence) error.value = cause instanceof Error ? cause.message : '加载保留策略失败' }
  finally { if (seq === sequence) busy.value = false }
}
async function run(kind: 'save' | 'preview' | 'apply') {
  const seq = ++sequence, workspace = props.workspaceId
  error.value = ''; message.value = ''; busy.value = true
  try {
    let data
    if (kind === 'save') data = await api(`/workspaces/${workspace}/storage-policy`, 'PUT', { keep_history: keepHistory.value, revision: revision.value })
    else if (kind === 'preview') data = await api(`/workspaces/${workspace}/storage-cleanup/preview`, 'POST', { clear_parse_cache: parseCache.value, clear_embedding_cache: embeddingCache.value })
    else data = await api(`/workspaces/${workspace}/storage-cleanup/apply`, 'POST', { preview_id: preview.value.id, revision: preview.value.revision, confirm: true })
    if (seq !== sequence) return
    if (kind === 'save') { revision.value = data.revision; savedKeepHistory.value = data.keep_history; preview.value = null; message.value = '保留策略已保存；只在确认清理时执行。' }
    else if (kind === 'preview') { preview.value = data; pager.reset() }
    else { preview.value = null; message.value = `已清理 ${data.removed.length} 个目录，文件逻辑大小 ${size(data.freed_bytes)}。${data.status === 'partial' ? data.message : ''}`; emit('cleaned') }
  } catch (cause) {
    if (seq === sequence) { error.value = cause instanceof Error ? cause.message : '存储操作失败'; preview.value = null }
  } finally { if (seq === sequence) busy.value = false }
}
watch(() => props.workspaceId, load, { immediate: true })
watch([parseCache, embeddingCache, keepHistory], () => { preview.value = null })
onBeforeUnmount(() => { sequence++ })
</script>

<template>
  <details class="cleanup-panel">
    <summary>存储治理 · 保留策略与清理预览</summary>
    <div class="cleanup-body">
      <p class="muted">始终保护当前索引与在途任务；历史成功代际按完成时间保留。失败／未发布代际可清理。清理不删除项目、源码、Wiki、记忆或任务记录。</p>
      <div class="cleanup-toolbar"><label>额外保留历史成功代际<input v-model.number="keepHistory" type="number" min="0" max="100" :disabled="busy || !policyReady"></label><button :disabled="busy || !policyReady" @click="run('save')">保存保留策略</button><button v-if="!policyReady && !busy" @click="load">重试加载策略</button></div>
      <p class="muted">默认保留当前索引之外的 2 个历史成功代际；保存策略不会自动删除数据，改变数量后请先保存，再预览。</p>
      <div class="cleanup-options"><label><input v-model="parseCache" type="checkbox" :disabled="busy || !policyReady">同时清理解析缓存</label><label><input v-model="embeddingCache" type="checkbox" :disabled="busy || !policyReady">同时清理向量缓存</label></div>
      <p class="muted">缓存清理会增加下次索引的解析／模型开销；项目有在途任务时禁止清理缓存。</p>
      <button :disabled="busy || !policyReady || policyDirty" @click="run('preview')">{{ busy ? '处理中…' : '预览清理' }}</button>
      <p v-if="policyDirty" class="muted">保留数量已修改，请先保存保留策略。</p>
      <p v-if="error" role="alert" class="cleanup-error">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
      <section v-if="preview" class="cleanup-preview" aria-label="存储清理预览">
        <h3>待清理 {{ preview.candidates.length }} 个目录 · {{ preview.files.toLocaleString() }} 个文件 · {{ size(preview.bytes) }}</h3>
        <p class="muted">已保护 {{ preview.protected.length }} 个代际（其中额外保留 {{ preview.retained_history.length }} 个历史成功代际）。预览 15 分钟内有效，执行前重新核对文件与任务状态。</p>
        <div class="table-wrap"><table><thead><tr><th>服务数据相对目录</th><th>文件数</th><th>逻辑大小</th></tr></thead><tbody><tr v-for="item in pager.rows.value" :key="item.path"><td class="mono">{{ item.path }}</td><td>{{ item.files.toLocaleString() }}</td><td>{{ size(item.bytes) }}</td></tr></tbody></table></div>
        <Pagination :page="pager.page.value" :page-size="pager.pageSize.value" :total="pager.total.value" :pages="pager.pages.value" label="待清理目录" @change="pager.page.value=$event" @size="pager.pageSize.value=$event;pager.reset()"/>
        <p v-if="preview.skipped.length" class="muted">跳过 {{ preview.skipped.length }} 个符号链接或非目录条目。</p>
        <p v-if="!preview.candidates.length" class="muted">当前保留策略下没有可清理目录。</p>
        <div class="cleanup-toolbar"><button @click="preview=null" :disabled="busy">取消预览</button><button class="danger" @click="run('apply')" :disabled="busy || !preview.candidates.length">确认清理以上目录</button></div>
      </section>
    </div>
  </details>
</template>

<style scoped>
.cleanup-panel{border-top:1px solid var(--line);margin-top:20px;padding-top:18px}.cleanup-panel summary{cursor:pointer;color:#59637a;font-size:14px;font-weight:600}.cleanup-body{padding-top:12px}.cleanup-toolbar,.cleanup-options{display:flex;align-items:center;gap:18px;margin:18px 0}.cleanup-toolbar label,.cleanup-options label{display:flex;align-items:center;gap:12px;margin:0;color:#69738a;font-size:13px}.cleanup-toolbar input{width:85px}.cleanup-options input{width:auto;min-height:0;margin:0}.cleanup-preview{margin-top:20px;padding:18px;border:1px solid var(--line);border-radius:10px;background:#fafbff}.cleanup-preview h3{font-size:14px}.cleanup-error{color:#b94350}.cleanup-body p{line-height:1.8}
</style>
