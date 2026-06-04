<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getContinuityDashboard } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const data = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try { data.value = await getContinuityDashboard(workspace.value) } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Continuity Dashboard</h1>
    <DataCard :loading="loading" :error="error">
      <div v-if="data">
        <div class="stats-row">
          <div class="stat"><div class="stat-val">{{ data.focus_task?.title || 'None' }}</div><div class="stat-label">Focus</div></div>
          <div class="stat"><div class="stat-val">{{ data.resume_packet?.current_phase || '-' }}</div><div class="stat-label">Phase</div></div>
          <div class="stat"><div class="stat-val">{{ data.next_actions?.length || 0 }}</div><div class="stat-label">Next Actions</div></div>
          <div class="stat"><div class="stat-val">{{ data.unresolved_items?.length || 0 }}</div><div class="stat-label">Unresolved</div></div>
        </div>
        <details class="section" open><summary>Full Data</summary><JsonTree :data="data" label="continuity" :depth="0" /></details>
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.stats-row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.stat { background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; min-width: 120px; text-align: center; }
.stat-val { font-size: 18px; font-weight: 700; }
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; margin-top: 4px; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; font-size: 14px; color: #4a6fa5; }
</style>
