<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getDrillTask, listTaskSpaces } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const route = useRoute()
const taskId = ref(route.query.task_id || '')
const data = ref(null)
const tasks = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    tasks.value = await listTaskSpaces(workspace.value)
    if (taskId.value) {
      data.value = await getDrillTask(workspace.value, taskId.value)
    }
  } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Focus Task</h1>
    <div class="controls">
      <input v-model="taskId" placeholder="Task ID" @keyup.enter="load" />
      <button @click="load" :disabled="loading">Load</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="tasks?.task_spaces?.length" class="task-list">
        <div v-for="t in tasks.task_spaces" :key="t.task_id" class="task-item" @click="taskId = t.task_id; load()">
          <span class="task-title">{{ t.title || t.task_id }}</span>
          <span class="task-status">{{ t.status }}</span>
        </div>
      </div>
      <div v-if="data"><JsonTree :data="data" label="task" :depth="0" /></div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.controls { display: flex; gap: 8px; margin-bottom: 16px; }
.controls input, .controls button { padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }
.controls button { background: #4a6fa5; color: #fff; border: none; cursor: pointer; }
.task-list { margin-bottom: 16px; }
.task-item { display: flex; justify-content: space-between; padding: 8px 12px; border: 1px solid #eee; border-radius: 6px; margin-bottom: 4px; cursor: pointer; }
.task-item:hover { background: #f0f7ff; }
.task-title { font-weight: 600; font-size: 13px; }
.task-status { color: #888; font-size: 12px; }
</style>
