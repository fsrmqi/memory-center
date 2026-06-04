<script setup>
import { ref, inject, onMounted } from 'vue'
import { getVerificationLoop, getWorkflowProfile, getRuntimeAudit } from '../api/client.js'
import DataCard from '../components/DataCard.vue'

const workspace = inject('workspace')
const taskType = ref('general')
const verification = ref(null)
const profile = ref(null)
const runtimeAudit = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    verification.value = await getVerificationLoop(workspace, { task_type: taskType.value })
    profile.value = await getWorkflowProfile(taskType.value)
    runtimeAudit.value = await getRuntimeAudit(workspace)
  } catch (e) {
    verification.value = { error: e.message }
  }
  loading.value = false
}

onMounted(load)
</script>
<template>
  <div class="p-6">
    <h1 class="text-xl font-bold mb-4">Verification & Workflow</h1>
    <div class="mb-4 flex gap-2 items-center">
      <select v-model="taskType" class="border rounded px-2 py-1">
        <option value="general">General</option>
        <option value="code_change">Code Change</option>
        <option value="feature">Feature</option>
        <option value="bugfix">Bug Fix</option>
        <option value="contract-change">Contract Change</option>
        <option value="long-task">Long Task</option>
        <option value="architecture">Architecture</option>
      </select>
      <button @click="load" class="bg-blue-500 text-white px-3 py-1 rounded">Refresh</button>
    </div>
    <div v-if="loading" class="text-gray-500">Loading...</div>
    <DataCard v-if="verification && !loading" title="Verification Checklist" :data="verification" />
    <DataCard v-if="profile && !loading" title="Workflow Profile" :data="profile" />
    <DataCard v-if="runtimeAudit && !loading" title="Runtime Audit" :data="runtimeAudit" />
  </div>
</template>