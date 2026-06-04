<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getWorkHealth, getDiscover } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const health = ref(null)
const discover = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    health.value = await getWorkHealth(workspace.value)
    discover.value = await getDiscover(workspace.value)
  } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Health & Discover</h1>
    <DataCard :loading="loading" :error="error">
      <div v-if="health" class="section">
        <h3>Work Health</h3>
        <JsonTree :data="health" label="health" :depth="0" />
      </div>
      <div v-if="discover" class="section">
        <h3>Discover</h3>
        <JsonTree :data="discover" label="discover" :depth="0" />
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.section { margin: 16px 0; }
.section h3 { font-size: 14px; margin: 0 0 8px; color: #333; }
</style>
