<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { getWorkHealth, getDiscover, getReplayCampaign } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const health = ref(null)
const discover = ref(null)
const replayCampaign = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    ;[health.value, discover.value, replayCampaign.value] = await Promise.all([
      getWorkHealth(workspace.value), getDiscover(workspace.value), getReplayCampaign(workspace.value),
    ])
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
      <div v-if="replayCampaign" class="section">
        <h3>Replay Campaign</h3>
        <div class="campaign-state" :class="replayCampaign.passed ? 'passed' : 'pending'">
          {{ replayCampaign.passed ? 'Ready for policy review' : 'More real replay coverage required' }}
        </div>
        <JsonTree :data="replayCampaign.coverage" label="coverage" :depth="0" />
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.section { margin: 16px 0; }
.section h3 { font-size: 14px; margin: 0 0 8px; color: #333; }
.campaign-state { margin-bottom: 8px; font-weight: 600; }
.campaign-state.passed { color: #17733a; }
.campaign-state.pending { color: #9a6700; }
</style>
