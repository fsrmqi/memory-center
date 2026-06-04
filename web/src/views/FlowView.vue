<script setup>
import { ref, inject } from 'vue'
import { getBusinessFlow, getBusinessFlowImpact } from '../api/client.js'
import DataCard from '../components/DataCard.vue'

const workspace = inject('workspace')
const seedNode = ref('')
const flows = ref(null)
const impact = ref(null)
const nodeId = ref('')
const loading = ref(false)

async function extractFlows() {
  if (!seedNode.value) return
  loading.value = true
  try {
    flows.value = await getBusinessFlow(workspace, seedNode.value)
  } catch (e) {
    flows.value = { error: e.message }
  }
  loading.value = false
}

async function checkImpact() {
  if (!nodeId.value) return
  loading.value = true
  try {
    impact.value = await getBusinessFlowImpact(workspace, nodeId.value)
  } catch (e) {
    impact.value = { error: e.message }
  }
  loading.value = false
}
</script>
<template>
  <div class="p-6">
    <h1 class="text-xl font-bold mb-4">Business Flow</h1>
    <div class="mb-4 flex gap-2">
      <input v-model="seedNode" placeholder="Seed Node ID" class="border rounded px-2 py-1 flex-1" />
      <button @click="extractFlows" class="bg-blue-500 text-white px-3 py-1 rounded">Extract Flows</button>
    </div>
    <DataCard v-if="flows" title="Extracted Flows" :data="flows" />
    <hr class="my-4" />
    <h2 class="text-lg font-bold mb-2">Flow Impact</h2>
    <div class="mb-4 flex gap-2">
      <input v-model="nodeId" placeholder="Node ID" class="border rounded px-2 py-1 flex-1" />
      <button @click="checkImpact" class="bg-green-500 text-white px-3 py-1 rounded">Check Impact</button>
    </div>
    <DataCard v-if="impact" title="Impacted Nodes" :data="impact" />
  </div>
</template>