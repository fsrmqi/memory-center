<script setup>
import { computed, ref, inject, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  exportWalkthrough, getCallees, getCallers, getMethodWalkthrough,
  getQualityGatesSummary, getSymbol, getWalkthroughEvaluation, queryWorkspace,
} from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const route = useRoute()
const query = ref('')
const mode = ref('auto')
const reportLevel = ref('standard')
const data = ref(null)
const walkthroughEvaluation = ref(null)
const exportResult = ref(null)
const exportGateSnapshot = ref(null)
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const completionStatus = computed(() => data.value?.completion_status || data.value?.result?.completion_status || null)
const walkthrough = computed(() => mode.value === 'walkthrough' && data.value?.found !== false ? data.value : null)
const summaryLines = computed(() => walkthrough.value?.summary_lines || [])
const readTargets = computed(() => walkthrough.value?.read_targets || [])
const risks = computed(() => [
  ...(walkthrough.value?.performance_risks || []),
  ...(walkthrough.value?.data_scope_guards || []).filter((item) => item.status !== 'present'),
])

function applyRouteQuery() {
  const nextMode = String(route.query.mode || '')
  if (['auto', 'symbol', 'callers', 'callees', 'walkthrough'].includes(nextMode)) mode.value = nextMode
  if (route.query.symbol) query.value = String(route.query.symbol)
  if (route.query.report_level) reportLevel.value = String(route.query.report_level)
}

watch(() => route.query, applyRouteQuery, { immediate: true })

async function search() {
  if (!workspace.value || !query.value) return
  loading.value = true; error.value = ''; walkthroughEvaluation.value = null; exportResult.value = null; exportGateSnapshot.value = null
  try {
    if (mode.value === 'symbol') {
      data.value = await getSymbol(workspace.value, query.value)
    } else if (mode.value === 'callers') {
      data.value = await getCallers(workspace.value, query.value)
    } else if (mode.value === 'callees') {
      data.value = await getCallees(workspace.value, query.value)
    } else if (mode.value === 'walkthrough') {
      data.value = await getMethodWalkthrough(workspace.value, query.value, { report_level: reportLevel.value })
    } else {
      data.value = await queryWorkspace(workspace.value, query.value)
    }
  } catch (e) { error.value = e.message }
  loading.value = false
}

async function evaluateWalkthrough() {
  if (!workspace.value || !query.value) return
  try {
    walkthroughEvaluation.value = await getWalkthroughEvaluation(workspace.value, query.value, { report_level: reportLevel.value })
  } catch (e) { error.value = e.message }
}

async function exportCurrentWalkthrough() {
  if (!workspace.value || !query.value) return
  exporting.value = true; error.value = ''
  try {
    const [exported, gates] = await Promise.all([
      exportWalkthrough(workspace.value, query.value, { report_level: 'deep' }),
      getQualityGatesSummary(workspace.value),
    ])
    exportResult.value = exported
    exportGateSnapshot.value = gates
  } catch (e) { error.value = e.message }
  exporting.value = false
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
        <option value="walkthrough">Walkthrough</option>
      </select>
      <select v-if="mode === 'walkthrough'" v-model="reportLevel" aria-label="Walkthrough detail level">
        <option value="summary">Summary</option>
        <option value="standard">Standard</option>
        <option value="deep">Deep</option>
      </select>
      <button @click="search" :disabled="loading || !query">Search</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <section v-if="walkthrough" class="walkthrough-summary">
          <div class="walkthrough-heading">
            <div><span>Walkthrough</span><strong>{{ walkthrough.target?.class }}#{{ walkthrough.target?.method }}</strong></div>
            <div class="walkthrough-actions">
              <button @click="evaluateWalkthrough">Evaluate</button>
              <button @click="exportCurrentWalkthrough" :disabled="exporting">{{ exporting ? 'Exporting...' : 'Export report' }}</button>
            </div>
          </div>
          <div v-if="summaryLines.length" class="quick-conclusion"><h2>Quick conclusion</h2><p v-for="(line, index) in summaryLines" :key="index">{{ line }}</p></div>
          <div v-if="readTargets.length" class="read-targets"><h2>Main chain</h2><ol><li v-for="(target, index) in readTargets" :key="`${target.role}-${index}`"><b>{{ target.role }}</b><span>{{ target.label || 'indexed target' }}</span></li></ol></div>
          <div v-if="risks.length" class="risk-list"><h2>Risks</h2><ul><li v-for="(risk, index) in risks" :key="`${risk.code || risk.message}-${index}`"><b>{{ risk.severity || risk.status || 'review' }}</b> {{ risk.code || risk.message }}</li></ul></div>
          <div v-if="walkthrough.next_actions?.length" class="next-actions"><h2>Next actions</h2><ul><li v-for="action in walkthrough.next_actions" :key="action">{{ action }}</li></ul></div>
          <div v-if="walkthroughEvaluation" class="evaluation"><b>Walkthrough quality: {{ walkthroughEvaluation.grade }}</b><span>{{ walkthroughEvaluation.score }}/100</span></div>
          <div v-if="exportResult" class="export-result"><b>Exported:</b> {{ exportResult.artifact }}<span v-if="exportGateSnapshot"> Gate snapshot: {{ exportGateSnapshot.health }}, {{ exportGateSnapshot.benchmark.score }}/100</span></div>
        </section>
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
        <details class="section"><summary>Evidence details / Full response</summary><JsonTree :data="data" label="query" :depth="0" /></details>
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
.walkthrough-summary { border: 1px solid #d9e2ef; border-radius: 8px; background: #fff; padding: 14px; margin-bottom: 14px; }
.walkthrough-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.walkthrough-heading span { display: block; color: #667085; font-size: 12px; text-transform: uppercase; }.walkthrough-heading strong { display: block; margin-top: 3px; font-size: 16px; overflow-wrap: anywhere; }.walkthrough-actions { display: flex; gap: 8px; flex-wrap: wrap; }.walkthrough-actions button { padding: 7px 10px; border: 1px solid #4a6fa5; border-radius: 6px; background: #fff; color: #2d568c; cursor: pointer; font-size: 12px; }.walkthrough-actions button:last-child { background: #4a6fa5; color: #fff; }
.quick-conclusion, .read-targets, .risk-list, .next-actions { margin-top: 14px; }.walkthrough-summary h2 { margin: 0 0 6px; font-size: 13px; }.quick-conclusion p { margin: 4px 0; color: #344054; font-size: 13px; }.read-targets ol, .risk-list ul, .next-actions ul { margin: 0; padding-left: 20px; color: #344054; font-size: 13px; }.read-targets li { margin: 5px 0; }.read-targets b { display: inline-block; min-width: 132px; color: #2d568c; }.read-targets span { overflow-wrap: anywhere; }.risk-list b { text-transform: uppercase; font-size: 11px; color: #a15c00; }.evaluation, .export-result { margin-top: 14px; padding: 9px 10px; border-radius: 6px; background: #f4f8fd; font-size: 13px; }.evaluation span { margin-left: 8px; color: #2d568c; font-weight: 700; }.export-result span { margin-left: 8px; color: #667085; }
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
@media (max-width: 700px) { .controls { flex-wrap: wrap; }.search-input { flex-basis: 100%; }.walkthrough-heading { flex-direction: column; }.read-targets b { min-width: 0; margin-right: 6px; } }
</style>
