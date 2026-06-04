<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getBackendQuery, getBackendConsistency } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const data = ref(null)
const consistency = ref(null)
const loading = ref(false)
const error = ref('')
const collection = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    const params = collection.value ? { collection: collection.value } : {}
    data.value = await getBackendQuery(workspace.value, params)
    consistency.value = await getBackendConsistency(workspace.value)
  } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Backend / Memory DB</h1>
    <div class="controls">
      <input v-model="collection" placeholder="Collection (optional)" @keyup.enter="load" />
      <button @click="load" :disabled="loading">Refresh</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="consistency" class="consistency"><JsonTree :data="consistency" label="consistency" :depth="0" /></div>
      <details class="section" open><summary>Backend Data</summary><JsonTree :data="data" label="backend" :depth="0" /></details>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.controls { display: flex; gap: 8px; margin-bottom: 16px; }
.controls input { padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; }
.controls button { padding: 6px 12px; background: #4a6fa5; color: #fff; border: none; border-radius: 6px; cursor: pointer; }
.consistency { margin-bottom: 16px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
</style>
