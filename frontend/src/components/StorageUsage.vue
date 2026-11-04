<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'
import StorageCleanup from './StorageCleanup.vue'

type Usage = {
  observed_at: string; partial: boolean; accounted_bytes: number
  files: { total_bytes: number; current_generation_bytes: number; other_generations_bytes: number; parse_cache_bytes: number; embedding_cache_bytes: number; other_bytes: number; file_count: number; read_errors: number; skipped_symlinks: number }
  database: { payload_bytes: number; chunks: { count: number; text_bytes: number; vector_count: number; vector_json_bytes: number; native_vector_bytes: number }; terms: { count: number; text_bytes: number }; records: { kind: string; count: number; text_bytes: number }[] }
  shared_database: { backend: string; physical_bytes: number | null; read_errors?: number }
}
const props = defineProps<{ workspaceId: string; name: string }>()
const usage = ref<Usage | null>(null), loading = ref(false), error = ref('')
let requestId = 0
const labels: Record<string, string> = { memory: '项目记忆', wiki: '受管 Wiki', session: '会话', job: '索引任务', index: '索引元数据' }
function bytes(value: number) {
  if (value < 1024) return `${value.toLocaleString()} B`
  const unit = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)))
  return `${(value / 1024 ** unit).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${['B', 'KiB', 'MiB', 'GiB', 'TiB'][unit]}`
}
async function refresh() {
  const id = ++requestId
  usage.value = null; error.value = ''; loading.value = true
  try {
    const result = await api(`/workspaces/${props.workspaceId}/storage`)
    if (id === requestId) usage.value = result
  } catch (cause) {
    if (id === requestId) error.value = cause instanceof Error ? cause.message : '无法读取空间占用'
  } finally {
    if (id === requestId) loading.value = false
  }
}
watch(() => props.workspaceId, refresh, { immediate: true })
onBeforeUnmount(() => { requestId++ })
</script>

<template>
  <section class="storage-panel" aria-label="项目空间占用" :aria-busy="loading">
    <div class="storage-heading"><div><h2>{{ name }} · 空间占用</h2><p class="muted">服务端项目数据，按需统计；源码与外部 Wiki 目录不计入。</p></div><button @click="refresh" :disabled="loading">{{ loading ? '统计中…' : '刷新占用' }}</button></div>
    <p v-if="loading" role="status">正在读取项目文件与数据库统计…</p>
    <p v-else-if="error" role="alert" class="storage-error">{{ error }}，可点击刷新重试。</p>
    <template v-else-if="usage">
      <div class="storage-metrics">
        <div><span>已统计数据量</span><strong>{{ bytes(usage.accounted_bytes) }}</strong><small>文件大小 + 数据库载荷</small></div>
        <div><span>索引与缓存文件</span><strong>{{ bytes(usage.files.total_bytes) }}</strong><small>{{ usage.files.file_count.toLocaleString() }} 个文件</small></div>
        <div><span>项目数据库载荷</span><strong>{{ bytes(usage.database.payload_bytes) }}</strong><small>{{ usage.database.chunks.count.toLocaleString() }} 个分块</small></div>
        <div><span>向量载荷</span><strong>{{ bytes(usage.database.chunks.vector_json_bytes + usage.database.chunks.native_vector_bytes) }}</strong><small>{{ usage.database.chunks.vector_count.toLocaleString() }} 个向量 · 已包含在数据库载荷中</small></div>
      </div>
      <div class="storage-breakdown">
        <div><h3>项目文件</h3><dl><dt>当前索引代际</dt><dd>{{ bytes(usage.files.current_generation_bytes) }}</dd><dt>其他代际（含历史／未发布）</dt><dd>{{ bytes(usage.files.other_generations_bytes) }}</dd><dt>代码解析缓存</dt><dd>{{ bytes(usage.files.parse_cache_bytes) }}</dd><dt>向量缓存</dt><dd>{{ bytes(usage.files.embedding_cache_bytes) }}</dd><dt>其他项目文件</dt><dd>{{ bytes(usage.files.other_bytes) }}</dd></dl></div>
        <div><h3>数据库载荷明细</h3><dl><dt>分块文本、元数据与向量 JSON</dt><dd>{{ bytes(usage.database.chunks.text_bytes) }}</dd><dt>原生向量列</dt><dd>{{ bytes(usage.database.chunks.native_vector_bytes) }}</dd><dt>关键词索引文本</dt><dd>{{ bytes(usage.database.terms.text_bytes) }}</dd><template v-for="record in usage.database.records" :key="record.kind"><dt>{{ labels[record.kind] || record.kind }} · {{ record.count.toLocaleString() }} 条</dt><dd>{{ bytes(record.text_bytes) }}</dd></template></dl></div>
      </div>
      <p v-if="usage.partial" class="storage-error" role="status">统计不完整：{{ usage.files.read_errors }} 项读取失败，{{ usage.files.skipped_symlinks }} 个符号链接已跳过。显示值仅为已读取部分。</p>
      <p class="muted storage-note">文件按逻辑大小统计；数据库按项目文本的 UTF-8 字节与原生向量列载荷统计，未包含数据库页、关系索引、整数列及控制面目录记录。共享存储不能精确分摊，因此数据量不等于实际磁盘占用。向量载荷是数据库载荷的子项，不重复累计。</p>
      <p class="muted">{{ usage.shared_database.backend === 'sqlite' ? `共享 SQLite 文件大小：${bytes(usage.shared_database.physical_bytes || 0)}（全部项目，含 WAL／SHM，不计入本项目）` : 'PostgreSQL 物理页与向量索引由全部项目共享，不分摊到本项目。' }}<span v-if="usage.shared_database.read_errors"> · 共享文件统计不完整</span></p>
      <p class="muted">统计时间：{{ new Date(usage.observed_at).toLocaleString() }}。索引运行期间数据仍会变化，可手动刷新。</p>
    </template>
    <StorageCleanup :workspace-id="workspaceId" @cleaned="refresh"/>
  </section>
</template>

<style scoped>
.storage-panel{margin-top:24px;padding:24px;background:white;border:1px solid var(--line);border-radius:14px}
.storage-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:20px}.storage-heading h2{margin:0 0 8px}.storage-heading p{margin:0}
.storage-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.storage-metrics>div{background:#f7f8fd;border:1px solid var(--line);border-radius:10px;padding:18px}.storage-metrics span,.storage-metrics small{display:block;color:#79839a;font-size:12px;line-height:1.7}.storage-metrics strong{display:block;font-size:25px;color:#434b65;margin:8px 0}
.storage-breakdown{display:grid;grid-template-columns:1fr 1fr;gap:36px;margin-top:24px}.storage-breakdown h3{font-size:14px}.storage-breakdown dl{display:grid;grid-template-columns:minmax(0,1fr) auto;font-size:13px;gap:12px 20px}.storage-breakdown dt{color:#79839a;overflow-wrap:anywhere}.storage-breakdown dd{margin:0;font-variant-numeric:tabular-nums;color:#434b65}.storage-note{border-top:1px solid var(--line);padding-top:18px;line-height:1.8}.storage-error{color:#b94350}
</style>
