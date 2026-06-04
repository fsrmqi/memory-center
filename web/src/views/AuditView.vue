<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getAudit, getBenchmarkTrend } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const auditData = ref(null)
const trendData = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    auditData.value = await getAudit(workspace.value)
    trendData.value = await getBenchmarkTrend(workspace.value)
  } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Audit & Benchmark</h1>
    <DataCard :loading="loading" :error="error">
      <div v-if="auditData" class="section">
        <h3>Completion Audit</h3>
        <div class="stats-row" v-if="auditData.score !== undefined">
          <div class="stat"><div class="stat-val">{{ auditData.score }}</div><div class="stat-label">Score</div></div>
          <div class="stat"><div class="stat-val">{{ auditData.findings?.length || 0 }}</div><div class="stat-label">Findings</div></div>
        </div>
        <JsonTree :data="auditData" label="audit" :depth="0" />
      </div>
      <div v-if="trendData" class="section">
        <h3>Benchmark Trend</h3>
        <JsonTree :data="trendData" label="trend" :depth="0" />
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.section { margin: 16px 0; }
.section h3 { font-size: 14px; margin: 0 0 8px; color: #333; }
.stats-row { display: flex; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
.stat { background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; min-width: 100px; text-align: center; }
.stat-val { font-size: 18px; font-weight: 700; }
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; margin-top: 4px; }
</style>
