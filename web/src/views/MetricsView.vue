<script setup>
import { ref, onMounted } from 'vue'
import { getMetricsSummary } from '../api/client.js'
import DataCard from '../components/DataCard.vue'

const metrics = ref(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    metrics.value = await getMetricsSummary()
  } catch (e) {
    metrics.value = { error: e.message }
  }
  loading.value = false
})
</script>
<template>
  <div class="p-6">
    <h1 class="text-xl font-bold mb-4">Metrics Summary</h1>
    <div v-if="loading" class="text-gray-500">Loading...</div>
    <DataCard v-if="metrics && !loading" title="Metrics" :data="metrics" />
  </div>
</template>