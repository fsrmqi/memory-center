<script setup>
import { computed, ref, inject } from 'vue'
import { queryWorkspace, getSymbol, getCallers, getCallees } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const query = ref('')
const mode = ref('auto')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const completionStatus = computed(() => data.value?.completion_status || data.value?.result?.completion_status || null)

async function search() {
  if (!workspace.value || !query.value) return
  loading.value = true; error.value = ''
  try {
    if (mode.value === 'symbol') {
      data.value = await getSymbol(workspace.value, query.value)
    } else if (mode.value === 'callers') {
      data.value = await getCallers(workspace.value, query.value)
    } else if (mode.value === 'callees') {
      data.value = await getCallees(workspace.value, query.value)
    } else {
      data.value = await queryWorkspace(workspace.value, query.value)
    }
  } catch (e) { error.value = e.message }
  loading.value = false
}
</script>
<template>
  <div>
    <h1>Query / Lookup</h1>
    <div class="controls">
      <input v-model="query" placeholder="Search text, symbol, or class name..." @keyup.enter="search" class="search-input" />
      <select v-model="mode">
        <option value="auto">Auto</option>
        <option value="symbol">Symbol</option>
        <option value="callers">Callers</option>
        <option value="callees">Callees</option>
      </select>
      <button @click="search" :disabled="loading || !query">Search</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <div v-if="completionStatus" class="completion-card" :class="`state-${completionStatus.state || 'unknown'}`">
          <div>
            <span class="completion-label">Completion</span>
            <strong>{{ completionStatus.state || 'unknown' }}</strong>
          </div>
          <div class="completion-meta">
            <span v-if="completionStatus.terminal_anchor">terminal: {{ completionStatus.terminal_anchor }}</span>
            <span>action: {{ completionStatus.recommended_action || 'n/a' }}</span>
            <span v-if="completionStatus.missing_layers?.length">missing: {{ completionStatus.missing_layers.join(', ') }}</span>
          </div>
        </div>
        <div v-if="data.matches?.length || data.results?.length" class="result-list">
          <div v-for="(item, i) in (data.matches || data.results)" :key="i" class="result-item">
            <span class="r-type">{{ item.node?.type || item.type || '' }}</span>
            <span class="r-name">{{ item.node?.name || item.name || '' }}</span>
            <span class="r-project">{{ item.node?.project || item.project || '' }}</span>
            <span class="r-score" v-if="item.score">{{ (item.score * 100).toFixed(0) }}%</span>
          </div>
        </div>
        <details class="section" open><summary>Full Response</summary><JsonTree :data="data" label="query" :depth="0" /></details>
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.controls { display: flex; gap: 8px; margin-bottom: 16px; }
.search-input { flex: 1; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
.controls select, .controls button { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }
.controls button { background: #4a6fa5; color: #fff; border: none; cursor: pointer; }
.result-item { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; align-items: center; }
.r-type { background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.r-name { font-weight: 600; color: #1a1a2e; }
.r-project { color: #888; font-size: 12px; }
.r-score { color: #28a745; font-weight: 600; font-size: 12px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
.completion-card { border: 1px solid #d9e2ef; border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; background: #f8fbff; display: flex; flex-direction: column; gap: 6px; }
.completion-card strong { margin-left: 8px; color: #1a1a2e; }
.completion-label { color: #4a6fa5; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.completion-meta { display: flex; gap: 12px; flex-wrap: wrap; color: #666; font-size: 12px; }
.completion-card.state-complete { border-color: #b7dfc3; background: #f4fbf6; }
.completion-card.state-partial { border-color: #f0d58a; background: #fffaf0; }
.completion-card.state-blocked, .completion-card.state-stale { border-color: #efb7b7; background: #fff6f6; }
</style>
