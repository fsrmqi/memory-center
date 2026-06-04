<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getReceipts } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const data = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try { data.value = await getReceipts(workspace.value) } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Write Receipts</h1>
    <DataCard :loading="loading" :error="error">
      <div v-if="data?.receipts?.length" class="receipt-list">
        <div v-for="(r, i) in data.receipts" :key="i" class="receipt-item">
          <span class="r-layer">{{ r.layer }}</span>
          <span class="r-action">{{ r.action }}</span>
          <span class="r-summary">{{ r.summary || '' }}</span>
        </div>
      </div>
      <details class="section"><summary>Full Data</summary><JsonTree :data="data" label="receipts" :depth="0" /></details>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.receipt-item { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.r-layer { color: #4a6fa5; font-weight: 600; min-width: 120px; }
.r-action { color: #888; min-width: 100px; }
.r-summary { color: #333; flex: 1; }
.section { margin: 12px 0; }
.section summary { cursor: pointer; font-weight: 600; color: #4a6fa5; }
</style>
