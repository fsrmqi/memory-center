<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getWorkspaceDashboard } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const route = useRoute()
const data = ref(null)
const loading = ref(false)
const error = ref('')
const intent = ref('')
const view = ref('compact')
const budget = ref('medium')

async function load() {
  if (!workspace.value) return
  loading.value = true
  error.value = ''
  try {
    data.value = await getWorkspaceDashboard(workspace.value, { intent: intent.value, view: view.value, budget: budget.value })
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}

onMounted(load)
watch(workspace, load)
</script>

<template>
  <div>
    <h1>Dashboard</h1>
    <div class="controls">
      <input v-model="intent" placeholder="Intent (optional)" @keyup.enter="load" />
      <select v-model="view"><option value="compact">Compact</option><option value="full">Full</option></select>
      <select v-model="budget"><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select>
      <button @click="load" :disabled="loading">Refresh</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <div class="stats-row">
          <div class="stat">
            <div class="stat-val">{{ data.focus_task?.title || 'None' }}</div>
            <div class="stat-label">Focus Task</div>
          </div>
          <div class="stat">
            <div class="stat-val">{{ data.active_tasks?.length || 0 }}</div>
            <div class="stat-label">Active Tasks</div>
          </div>
          <div class="stat">
            <div class="stat-val">{{ data.blocked_tasks?.length || 0 }}</div>
            <div class="stat-label">Blocked</div>
          </div>
          <div class="stat">
            <div class="stat-val">{{ data.low_quality_tasks?.length || 0 }}</div>
            <div class="stat-label">Low Quality</div>
          </div>
        </div>
        <details v-if="data.focus_resume_eval" class="section">
          <summary>Focus Resume Eval</summary>
          <JsonTree :data="data.focus_resume_eval" label="eval" :depth="0" />
        </details>
        <details v-if="data.active_tasks?.length" class="section">
          <summary>Active Tasks ({{ data.active_tasks.length }})</summary>
          <JsonTree :data="data.active_tasks" label="tasks" :depth="0" />
        </details>
        <details v-if="data.recent_receipts?.length" class="section">
          <summary>Recent Receipts</summary>
          <JsonTree :data="data.recent_receipts" label="receipts" :depth="0" />
        </details>
        <details v-if="data.tool_usage_report" class="section">
          <summary>Tool Usage Report</summary>
          <JsonTree :data="data.tool_usage_report" label="usage" :depth="0" />
        </details>
        <details class="section">
          <summary>Full Response</summary>
          <JsonTree :data="data" label="dashboard" :depth="0" />
        </details>
      </div>
    </DataCard>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 16px; }
.controls {
  display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;
}
.controls input, .controls select, .controls button {
  padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px;
}
.controls button {
  background: #4a6fa5; color: #fff; border: none; cursor: pointer;
}
.controls button:disabled { opacity: 0.5; }
.stats-row {
  display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
}
.stat {
  background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; min-width: 120px; text-align: center;
}
.stat-val { font-size: 18px; font-weight: 700; color: #1a1a2e; }
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; margin-top: 4px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; font-size: 14px; color: #4a6fa5; }
</style>
