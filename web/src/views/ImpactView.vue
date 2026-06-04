<script setup>
import { ref, inject } from 'vue'
import { getDrillRef } from '../api/client.js'
import axios from 'axios'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const target = ref('')
const direction = ref('upstream')
const depth = ref('standard')
const data = ref(null)
const loading = ref(false)
const error = ref('')

async function analyze() {
  if (!workspace.value || !target.value) return
  loading.value = true; error.value = ''
  try {
    const resp = await axios.get('/api/workspace/memory-context', {
      params: { workspace: workspace.value, name: target.value }
    })
    data.value = resp.data
  } catch (e) { error.value = e.message }
  loading.value = false
}
</script>
<template>
  <div>
    <h1>Impact / Context Analysis</h1>
    <div class="controls">
      <input v-model="target" placeholder="Target (class, method, endpoint...)" @keyup.enter="analyze" class="search-input" />
      <select v-model="direction"><option value="upstream">Upstream</option><option value="downstream">Downstream</option><option value="both">Both</option></select>
      <button @click="analyze" :disabled="loading || !target">Analyze</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <div v-if="data.found === false" class="not-found">No matching node found for "{{ target }}"</div>
        <div v-else>
          <div class="stats-row">
            <div class="stat"><div class="stat-val">{{ data.node?.type || '-' }}</div><div class="stat-label">Type</div></div>
            <div class="stat"><div class="stat-val">{{ data.incoming?.length || 0 }}</div><div class="stat-label">Incoming</div></div>
            <div class="stat"><div class="stat-val">{{ data.outgoing?.length || 0 }}</div><div class="stat-label">Outgoing</div></div>
          </div>
        </div>
        <details class="section" open><summary>Full Response</summary><JsonTree :data="data" label="impact" :depth="0" /></details>
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
.not-found { color: #dc3545; padding: 12px; background: #fff5f5; border-radius: 6px; }
.stats-row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.stat { background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; min-width: 100px; text-align: center; }
.stat-val { font-size: 18px; font-weight: 700; }
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; margin-top: 4px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
</style>
