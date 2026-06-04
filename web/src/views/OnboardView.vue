<script setup>
import { ref, inject, onMounted } from 'vue'
import { getOnboard } from '../api/client.js'
import DataCard from '../components/DataCard.vue'

const workspace = inject('workspace')
const persona = ref('developer')
const tour = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    tour.value = await getOnboard(workspace, { persona: persona.value })
  } catch (e) {
    tour.value = { error: e.message }
  }
  loading.value = false
}

onMounted(load)
</script>
<template>
  <div class="p-6">
    <h1 class="text-xl font-bold mb-4">Guided Tour / Onboarding</h1>
    <div class="mb-4 flex gap-2 items-center">
      <select v-model="persona" class="border rounded px-2 py-1">
        <option value="developer">Developer</option>
        <option value="architect">Architect</option>
        <option value="product">Product</option>
        <option value="tester">Tester</option>
      </select>
      <button @click="load" class="bg-blue-500 text-white px-3 py-1 rounded">Generate Tour</button>
    </div>
    <div v-if="loading" class="text-gray-500">Loading...</div>
    <DataCard v-if="tour && !loading" title="Architecture Tour" :data="tour" />
  </div>
</template>