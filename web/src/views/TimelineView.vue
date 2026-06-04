<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getDrillTimeline } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const limit = ref(30)

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try { data.value = await getDrillTimeline(workspace.value, { limit: limit.value }) } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Timeline</h1>
    <div class="controls">
      <label>Limit <input v-model.number="limit" type="number" min="1" max="200" style="width:60px" /></label>
      <button @click="load" :disabled="loading">Refresh</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data?.timeline?.length">
        <div v-for="(item, i) in data.timeline" :key="i" class="timeline-item">
          <span class="tl-time">{{ item.created_at || item.timestamp || '' }}</span>
          <span class="tl-kind">{{ item.kind || item.type || '' }}</span>
          <span class="tl-summary">{{ item.summary || item.label || '' }}</span>
        </div>
      </div>
      <details class="section"><summary>Full Data</summary><JsonTree :data="data" label="timeline" :depth="0" /></details>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.controls { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; }
.controls label { font-size: 13px; }
.controls input { padding: 4px 8px; border: 1px solid #ddd; border-radius: 4px; }
.controls button { padding: 6px 12px; background: #4a6fa5; color: #fff; border: none; border-radius: 6px; cursor: pointer; }
.timeline-item { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.tl-time { color: #888; white-space: nowrap; min-width: 160px; }
.tl-kind { color: #4a6fa5; font-weight: 600; min-width: 100px; }
.tl-summary { color: #333; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
</style>
