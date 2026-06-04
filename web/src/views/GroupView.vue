<script setup>
import { ref, inject } from 'vue'
import { getGroupStatus, groupQuery, groupImpact } from '../api/client.js'
import axios from 'axios'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const group = ref(localStorage.getItem('mc_group') || '')
const query = ref('')
const target = ref('')
const mode = ref('status')
const data = ref(null)
const loading = ref(false)
const error = ref('')

import { watch } from 'vue'
watch(group, (v) => localStorage.setItem('mc_group', v))

async function run() {
  if (!group.value) return
  loading.value = true; error.value = ''
  try {
    if (mode.value === 'status') {
      data.value = await getGroupStatus(group.value)
    } else if (mode.value === 'query') {
      if (!query.value) { error.value = 'Query required'; loading.value = false; return }
      data.value = await groupQuery(group.value, query.value)
    } else if (mode.value === 'impact') {
      if (!target.value) { error.value = 'Target required'; loading.value = false; return }
      data.value = await groupImpact(group.value, target.value)
    } else if (mode.value === 'chain') {
      if (!query.value) { error.value = 'Symbol required'; loading.value = false; return }
      const resp = await axios.get('/api/workspace/eval-regression-suite', {
        params: { workspace: workspace.value, group: group.value, symbol: query.value }
      })
      data.value = resp.data
    }
  } catch (e) { error.value = e.message }
  loading.value = false
}
</script>
<template>
  <div>
    <h1>Cross-Project / Group</h1>
    <div class="controls">
      <input v-model="group" placeholder="Group name" class="group-input" />
      <select v-model="mode">
        <option value="status">Status</option>
        <option value="query">Query</option>
        <option value="impact">Impact</option>
        <option value="chain">Chain</option>
      </select>
      <input v-if="mode === 'query' || mode === 'chain'" v-model="query" placeholder="Query / Symbol" @keyup.enter="run" class="search-input" />
      <input v-if="mode === 'impact'" v-model="target" placeholder="Target" @keyup.enter="run" class="search-input" />
      <button @click="run" :disabled="loading || !group">Run</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <div v-if="data.bridge_reasons?.length" class="bridges">
          <h3>Bridge Reasons</h3>
          <div v-for="(b, i) in data.bridge_reasons" :key="i" class="bridge-item">{{ b }}</div>
        </div>
        <div v-if="data.cross_workspace_path_hint" class="path-hint">
          <strong>Path:</strong> {{ data.cross_workspace_path_hint }}
        </div>
        <details class="section" open><summary>Full Response</summary><JsonTree :data="data" label="group" :depth="0" /></details>
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.controls { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.group-input { width: 160px; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; }
.search-input { flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; }
.controls select, .controls button { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }
.controls button { background: #4a6fa5; color: #fff; border: none; cursor: pointer; }
.bridges { margin-bottom: 16px; }
.bridges h3 { font-size: 14px; margin: 0 0 8px; }
.bridge-item { font-size: 12px; padding: 4px 8px; background: #f0f7ff; border-radius: 4px; margin-bottom: 4px; color: #1565c0; }
.path-hint { font-size: 13px; color: #333; margin-bottom: 16px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
</style>
