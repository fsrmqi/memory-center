<script setup>
import { computed, ref, inject, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  archiveTaskSpace,
  autoArchiveTaskSpaces,
  getContinuityDashboard,
  getDrillTask,
  getNextActions,
  getResumePacket,
  getWorkspaceDashboard,
  listTaskSpaces,
  syncSniffArtifacts,
  updateTaskStatus,
} from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const route = useRoute()
const router = useRouter()

const selectedTaskId = ref(route.query.task_id || '')
const tasks = ref({ active_tasks: [], archived_tasks: [] })
const continuity = ref(null)
const resumePacket = ref(null)
const nextActions = ref(null)
const taskDetail = ref(null)
const workspaceDashboard = ref(null)
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const actionMessage = ref('')
const includeArchived = ref(false)
const newIntent = ref('')
const newTitle = ref('')
const selectedStatus = ref('')
const archiveReason = ref('manual archive from Memory Space')
const retentionDays = ref(30)

const activeTasks = computed(() => tasks.value?.active_tasks || [])
const archivedTasks = computed(() => tasks.value?.archived_tasks || [])
const selectedTask = computed(() => {
  const all = [...activeTasks.value, ...archivedTasks.value]
  return all.find((task) => task.task_id === selectedTaskId.value) || null
})
const taskGroups = computed(() => {
  const active = activeTasks.value
  return [
    { key: 'active', label: '进行中 / Active', items: active.filter((task) => task.status === 'active') },
    { key: 'blocked', label: '阻塞 / Blocked', items: active.filter((task) => task.status === 'blocked') },
    { key: 'other', label: '其他状态 / Other', items: active.filter((task) => !['active', 'blocked'].includes(task.status)) },
    { key: 'archived', label: '已归档 / Archived', items: archivedTasks.value },
  ].filter((group) => group.items.length)
})
const nextActionItems = computed(() => nextActions.value?.action_items || [])
const unresolvedItems = computed(() => continuity.value?.unresolved_items || [])
const recentEvidence = computed(() => continuity.value?.recent_evidence || [])
const recentReceipts = computed(() => continuity.value?.recent_receipts || [])
const taskSummary = computed(() => {
  const packet = resumePacket.value || continuity.value?.resume_packet || {}
  return packet.current_summary || selectedTask.value?.summary_preview || ''
})
const lowQualityTasks = computed(() => workspaceDashboard.value?.low_quality_tasks || [])
const attentionTasks = computed(() => {
  const lowQualityIds = new Set(lowQualityTasks.value.map((task) => task.task_id))
  const rows = []
  for (const task of activeTasks.value) {
    const reasons = []
    if (lowQualityIds.has(task.task_id)) reasons.push('质量偏低')
    if (!task.summary_preview) reasons.push('缺少 current_summary')
    const staleDays = daysSince(task.updated_at || task.created_at)
    if (staleDays !== null && staleDays >= 14) reasons.push(`${staleDays} 天未更新`)
    if (task.status === 'blocked') reasons.push('状态阻塞')
    if (reasons.length) rows.push({ ...task, reasons })
  }
  return rows
})
const resumeText = computed(() => formatResumePacket(resumePacket.value, nextActionItems.value, unresolvedItems.value))

async function load() {
  if (!workspace.value) {
    error.value = '请先填写 workspace.yaml 路径。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const listed = await listTaskSpaces(workspace.value, { include_archived: includeArchived.value })
    tasks.value = listed || { active_tasks: [], archived_tasks: [] }
    try {
      workspaceDashboard.value = await getWorkspaceDashboard(workspace.value, { view: 'full', limit: 20 })
    } catch {
      workspaceDashboard.value = null
    }
    if (!selectedTaskId.value) {
      selectedTaskId.value = activeTasks.value[0]?.task_id || ''
    }
    await loadSelectedTask()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadSelectedTask() {
  continuity.value = null
  resumePacket.value = null
  nextActions.value = null
  taskDetail.value = null
  if (!workspace.value || !selectedTaskId.value) return

  const params = { task_id: selectedTaskId.value, view: 'full', limit: 8 }
  const [continuityResult, resumeResult, actionsResult, detailResult] = await Promise.all([
    getContinuityDashboard(workspace.value, params),
    getResumePacket(workspace.value, params),
    getNextActions(workspace.value, { task_id: selectedTaskId.value, limit: 8 }),
    getDrillTask(workspace.value, selectedTaskId.value),
  ])
  continuity.value = continuityResult
  resumePacket.value = resumeResult
  nextActions.value = actionsResult
  taskDetail.value = detailResult
  selectedStatus.value = selectedTask.value?.status || ''
  router.replace({
    query: { ...route.query, task_id: selectedTaskId.value, workspace: workspace.value },
  })
}

async function selectTask(taskId) {
  selectedTaskId.value = taskId
  loading.value = true
  error.value = ''
  try {
    await loadSelectedTask()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function runAction(action) {
  if (!workspace.value) {
    error.value = '请先填写 workspace.yaml 路径。'
    return
  }
  actionLoading.value = true
  error.value = ''
  actionMessage.value = ''
  try {
    const result = await action()
    actionMessage.value = actionResultMessage(result)
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    actionLoading.value = false
  }
}

async function syncIntent() {
  const intent = newIntent.value.trim()
  if (!intent) {
    error.value = '请输入任务意图。'
    return
  }
  await runAction(async () => {
    const result = await syncSniffArtifacts(workspace.value, intent, {
      title: newTitle.value.trim(),
      task_id: selectedTaskId.value,
      limit: 8,
      auto_sync_mode: 'balanced',
    })
    selectedTaskId.value = result.task_id || selectedTaskId.value
    newIntent.value = ''
    newTitle.value = ''
    return result
  })
}

async function changeSelectedStatus() {
  if (!selectedTaskId.value || !selectedStatus.value) return
  await runAction(() => updateTaskStatus(workspace.value, selectedTaskId.value, selectedStatus.value))
}

async function archiveSelectedTask() {
  if (!selectedTaskId.value) return
  await runAction(async () => {
    const result = await archiveTaskSpace(workspace.value, selectedTaskId.value, archiveReason.value)
    includeArchived.value = true
    selectedTaskId.value = activeTasks.value.find((task) => task.task_id !== result.task_id)?.task_id || result.task_id || ''
    return result
  })
}

async function autoArchiveStaleTasks() {
  await runAction(() => autoArchiveTaskSpaces(workspace.value, retentionDays.value))
  includeArchived.value = true
}

async function copyResumePacket() {
  if (!resumeText.value) {
    actionMessage.value = '当前没有可复制的恢复包。'
    return
  }
  try {
    await navigator.clipboard.writeText(resumeText.value)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = resumeText.value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
  actionMessage.value = '恢复包已复制。'
}

function statusLabel(status) {
  const labels = {
    active: '进行中',
    blocked: '阻塞',
    done: '完成',
    draft: '草稿',
    archived: '已归档',
  }
  return labels[status] || status || '未知'
}

function daysSince(value) {
  if (!value) return null
  const ts = Date.parse(value)
  if (Number.isNaN(ts)) return null
  return Math.floor((Date.now() - ts) / 86400000)
}

function actionResultMessage(result) {
  if (!result || typeof result !== 'object') return '操作已完成。'
  if (result.synced) return `已同步到任务空间：${result.title || result.task_id || ''}`
  if (result.updated) return `任务状态已更新：${result.status || ''}`
  if (result.archived) return `已归档：${result.title || result.task_id || ''}`
  if (typeof result.archived_count === 'number') return `自动归档完成：${result.archived_count} 个任务。`
  return '操作已完成。'
}

function formatResumePacket(packet, actions, unresolved) {
  if (!packet) return ''
  const lines = [
    '# Memory Center Resume Packet / 记忆空间恢复包',
    '',
    `Workspace: ${packet.workspace || ''}`,
    `Task: ${packet.task_title || packet.task_id || ''}`,
    `Task ID: ${packet.task_id || ''}`,
    `Phase: ${packet.current_phase || '-'}`,
    '',
    '## Current Summary / 当前摘要',
    packet.current_summary || '暂无摘要',
  ]
  if (actions?.length) {
    lines.push('', '## Next Actions / 下一步')
    for (const item of actions) {
      lines.push(`- [${item.priority || 'medium'}] ${item.action}`)
      if (item.reason) lines.push(`  Reason: ${item.reason}`)
    }
  }
  if (unresolved?.length) {
    lines.push('', '## Unresolved / 未解决项')
    for (const item of unresolved) lines.push(`- ${item}`)
  }
  if (packet.recent_evidence?.length) {
    lines.push('', '## Recent Evidence / 最近证据')
    for (const item of packet.recent_evidence.slice(0, 5)) {
      lines.push(`- ${item.summary || item.label || item.source || JSON.stringify(item)}`)
    }
  }
  return lines.join('\n')
}

onMounted(load)
watch(workspace, () => {
  selectedTaskId.value = route.query.task_id || ''
  load()
})
</script>

<template>
  <div class="memory-space">
    <div class="page-header">
      <div>
        <p class="eyebrow">Memory Space / 记忆空间</p>
        <h1>任务记忆工作台</h1>
        <p class="subtitle">从这里开始任务、同步上下文、恢复交接和清理过期任务。</p>
      </div>
      <div class="header-actions">
        <label class="archive-toggle">
          <input v-model="includeArchived" type="checkbox" @change="load" />
          包含归档
        </label>
        <button @click="load" :disabled="loading">刷新</button>
      </div>
    </div>

    <section class="operation-card">
      <div class="operation-main">
        <div>
          <h3>开始或同步任务 / Start or Sync</h3>
          <p class="muted">输入自然语言 intent，系统会匹配已有任务空间；匹配不够时自动创建。</p>
        </div>
        <div class="sync-form">
          <input
            v-model="newIntent"
            class="wide-input"
            placeholder="例如：梳理 ArticleMoveService 移动链路并补充验证计划"
            @keyup.enter="syncIntent"
          />
          <input
            v-model="newTitle"
            placeholder="任务标题，可选"
            @keyup.enter="syncIntent"
          />
          <button class="primary" :disabled="loading || actionLoading" @click="syncIntent">同步任务</button>
        </div>
      </div>
      <div class="cleanup-box">
        <h3>清理 / Cleanup</h3>
        <div class="inline-controls">
          <label>
            超过
            <input v-model.number="retentionDays" type="number" min="1" max="365" />
            天未更新
          </label>
          <button :disabled="loading || actionLoading" @click="autoArchiveStaleTasks">自动归档</button>
        </div>
      </div>
    </section>

    <div v-if="actionMessage" class="action-message">{{ actionMessage }}</div>

    <DataCard :loading="loading" :error="error">
      <div v-if="!activeTasks.length && !archivedTasks.length" class="empty-state">
        还没有任务空间。可在上方输入 intent，点击“同步任务”创建第一条任务记忆。
      </div>

      <div v-else class="workspace-grid">
        <aside class="task-sidebar">
          <section v-if="attentionTasks.length" class="attention-box">
            <h3>需要处理 / Needs Attention</h3>
            <button
              v-for="task in attentionTasks.slice(0, 5)"
              :key="task.task_id"
              class="attention-row"
              @click="selectTask(task.task_id)"
            >
              <strong>{{ task.title || task.task_id }}</strong>
              <span>{{ task.reasons.join('、') }}</span>
            </button>
          </section>

          <div
            v-for="group in taskGroups"
            :key="group.key"
            class="task-group"
          >
            <div class="group-title">{{ group.label }}</div>
            <button
              v-for="task in group.items"
              :key="task.task_id"
              class="task-row"
              :class="{ selected: task.task_id === selectedTaskId }"
              @click="selectTask(task.task_id)"
            >
              <span class="task-title">{{ task.title || task.task_id }}</span>
              <span class="task-meta">
                <span>{{ statusLabel(task.status) }}</span>
                <span v-if="task.priority">P: {{ task.priority }}</span>
              </span>
              <span class="task-time">{{ task.updated_at || task.created_at || '' }}</span>
            </button>
          </div>
        </aside>

        <section class="task-main">
          <div v-if="selectedTask" class="focus-card">
            <div class="focus-topline">
              <div>
                <p class="eyebrow">Focus Task / 当前任务</p>
                <h2>{{ selectedTask.title || selectedTask.task_id }}</h2>
              </div>
              <span class="status-pill" :class="selectedTask.status">{{ statusLabel(selectedTask.status) }}</span>
            </div>
            <div class="meta-grid">
              <div><span>Task ID</span><strong>{{ selectedTask.task_id }}</strong></div>
              <div><span>Priority</span><strong>{{ selectedTask.priority || 'medium' }}</strong></div>
              <div><span>Owner</span><strong>{{ selectedTask.owner || '-' }}</strong></div>
              <div><span>Updated</span><strong>{{ selectedTask.updated_at || '-' }}</strong></div>
            </div>
            <div v-if="selectedTask.tags?.length" class="tags">
              <span v-for="tag in selectedTask.tags" :key="tag">{{ tag }}</span>
            </div>

            <div class="task-actions">
              <label>
                状态
                <select v-model="selectedStatus" :disabled="actionLoading">
                  <option value="draft">草稿</option>
                  <option value="active">进行中</option>
                  <option value="blocked">阻塞</option>
                  <option value="done">完成</option>
                </select>
              </label>
              <button :disabled="actionLoading || !selectedStatus" @click="changeSelectedStatus">更新状态</button>
              <button :disabled="actionLoading" @click="copyResumePacket">复制恢复包</button>
              <button class="danger" :disabled="actionLoading" @click="archiveSelectedTask">归档任务</button>
            </div>

            <div class="summary-box">
              <h3>当前最短上下文 / Current Summary</h3>
              <pre v-if="taskSummary">{{ taskSummary }}</pre>
              <p v-else>暂无摘要。建议先同步一次任务上下文，避免下次恢复时缺少 L2 task space 信息。</p>
            </div>
          </div>

          <section v-if="resumeText" class="panel resume-copy-panel">
            <h3>恢复包预览 / Resume Packet Preview</h3>
            <pre>{{ resumeText }}</pre>
          </section>

          <div class="panel-grid">
            <section class="panel action-panel">
              <h3>下一步动作 / Next Actions</h3>
              <ol v-if="nextActionItems.length">
                <li v-for="item in nextActionItems" :key="item.action">
                  <div class="action-line">
                    <span class="priority" :class="item.priority">{{ item.priority || 'medium' }}</span>
                    <strong>{{ item.action }}</strong>
                  </div>
                  <p>{{ item.reason }}</p>
                </li>
              </ol>
              <p v-else class="muted">暂无下一步建议。</p>
            </section>

            <section class="panel">
              <h3>未解决项 / Unresolved</h3>
              <ul v-if="unresolvedItems.length" class="simple-list warning-list">
                <li v-for="item in unresolvedItems" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="muted">没有检测到待处理项。</p>
            </section>
          </div>

          <div class="panel-grid">
            <section class="panel">
              <h3>最近证据 / Recent Evidence</h3>
              <ul v-if="recentEvidence.length" class="simple-list">
                <li v-for="item in recentEvidence" :key="item.ref_id || item.created_at || item.summary">
                  <strong>{{ item.source || item.kind || 'evidence' }}</strong>
                  <span>{{ item.summary || item.label || item.event_type || item.action || '' }}</span>
                </li>
              </ul>
              <p v-else class="muted">暂无最近证据。</p>
            </section>

            <section class="panel">
              <h3>最近写入 / Recent Writes</h3>
              <ul v-if="recentReceipts.length" class="simple-list">
                <li v-for="item in recentReceipts" :key="item.receipt_id || item.created_at || item.target_file">
                  <strong>{{ item.action || item.kind || 'write' }}</strong>
                  <span>{{ item.target_file || item.target || item.summary || '' }}</span>
                </li>
              </ul>
              <p v-else class="muted">暂无写入记录。</p>
            </section>
          </div>

          <details class="raw-data">
            <summary>完整原始数据 / Raw Data</summary>
            <JsonTree
              :data="{ selectedTask, continuity, resumePacket, nextActions, taskDetail }"
              label="memory-space"
              :depth="0"
            />
          </details>
        </section>
      </div>
    </DataCard>
  </div>
</template>

<style scoped>
.memory-space { max-width: 1280px; }
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}
.eyebrow {
  color: #4a6fa5;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin-bottom: 4px;
  text-transform: uppercase;
}
h1 { font-size: 24px; margin: 0; }
h2 { font-size: 20px; margin: 0; }
h3 { font-size: 14px; margin: 0 0 10px; }
.subtitle { color: #667085; margin-top: 6px; }
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.archive-toggle {
  display: flex;
  gap: 6px;
  align-items: center;
  color: #475467;
  font-size: 13px;
}
button {
  border: 1px solid #d0d5dd;
  background: #fff;
  border-radius: 6px;
  color: #344054;
  cursor: pointer;
  font-size: 13px;
  padding: 7px 12px;
}
button:disabled { cursor: not-allowed; opacity: 0.65; }
.workspace-grid {
  display: grid;
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
  gap: 16px;
}
.task-sidebar {
  border-right: 1px solid #e4e7ec;
  padding-right: 14px;
}
.task-group + .task-group { margin-top: 18px; }
.group-title {
  color: #667085;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}
.task-row {
  display: block;
  width: 100%;
  border: 1px solid #e4e7ec;
  background: #fff;
  border-radius: 8px;
  margin-bottom: 8px;
  padding: 10px;
  text-align: left;
}
.task-row:hover { border-color: #98a2b3; }
.task-row.selected {
  background: #f0f7ff;
  border-color: #4a6fa5;
}
.task-title {
  color: #101828;
  display: block;
  font-weight: 700;
  line-height: 1.35;
}
.task-meta {
  color: #667085;
  display: flex;
  gap: 8px;
  font-size: 12px;
  margin-top: 6px;
}
.task-time {
  color: #98a2b3;
  display: block;
  font-size: 11px;
  margin-top: 4px;
}
.task-main { min-width: 0; }
.focus-card,
.panel {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  padding: 16px;
}
.focus-topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.status-pill,
.priority {
  border-radius: 999px;
  display: inline-flex;
  font-size: 12px;
  font-weight: 700;
  padding: 3px 8px;
  text-transform: uppercase;
}
.status-pill.active { background: #ecfdf3; color: #027a48; }
.status-pill.blocked { background: #fff4e5; color: #b54708; }
.status-pill.done { background: #eef4ff; color: #3538cd; }
.status-pill.archived { background: #f2f4f7; color: #475467; }
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.meta-grid div {
  background: #f9fafb;
  border-radius: 6px;
  padding: 10px;
  min-width: 0;
}
.meta-grid span {
  color: #667085;
  display: block;
  font-size: 11px;
  margin-bottom: 4px;
}
.meta-grid strong {
  color: #101828;
  display: block;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.tags span {
  background: #eef4ff;
  border-radius: 999px;
  color: #3538cd;
  font-size: 12px;
  padding: 3px 8px;
}
.summary-box {
  background: #f9fafb;
  border-radius: 8px;
  margin-top: 14px;
  padding: 14px;
}
.summary-box pre {
  color: #344054;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
}
.summary-box p,
.muted {
  color: #667085;
}
.panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.action-panel ol {
  display: grid;
  gap: 12px;
  list-style-position: inside;
}
.action-panel li { color: #344054; }
.action-line {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 4px;
}
.priority.high { background: #fef3f2; color: #b42318; }
.priority.medium { background: #fff8e6; color: #b54708; }
.priority.low { background: #ecfdf3; color: #027a48; }
.simple-list {
  display: grid;
  gap: 9px;
  list-style: none;
}
.simple-list li {
  background: #f9fafb;
  border-radius: 6px;
  color: #344054;
  display: grid;
  gap: 3px;
  padding: 10px;
}
.simple-list strong { color: #101828; font-size: 12px; }
.simple-list span { overflow-wrap: anywhere; }
.warning-list li { background: #fff8e6; }
.raw-data {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  margin-top: 14px;
  padding: 12px 16px;
}
.raw-data summary {
  color: #4a6fa5;
  cursor: pointer;
  font-weight: 700;
}
.empty-state {
  color: #667085;
  padding: 24px;
  text-align: center;
}
.empty-state code {
  background: #f2f4f7;
  border-radius: 4px;
  padding: 2px 5px;
}

@media (max-width: 900px) {
  .page-header,
  .focus-topline {
    flex-direction: column;
  }
  .workspace-grid,
  .panel-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }
  .task-sidebar {
    border-right: 0;
    border-bottom: 1px solid #e4e7ec;
    padding: 0 0 14px;
  }
}
</style>
