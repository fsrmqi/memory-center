<script setup>
import { inject, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { inspectAssertion, updateAssertionStatus } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const route = useRoute()
const assertionId = ref('')
const verificationRef = ref('')
const actor = ref('')
const taskId = ref('')
const sessionId = ref('')
const data = ref(null)
const error = ref('')
const loading = ref(false)

watch(() => route.query, (query) => {
  assertionId.value = String(query.assertion_id || assertionId.value || '')
  taskId.value = String(query.task_id || taskId.value || '')
  sessionId.value = String(query.session_id || sessionId.value || '')
  actor.value = String(query.actor || actor.value || '')
}, { immediate: true })

async function inspect() {
  if (!workspace.value || !assertionId.value) return
  loading.value = true; error.value = ''
  try { data.value = await inspectAssertion(workspace.value, assertionId.value) } catch (e) { error.value = e.message }
  loading.value = false
}

async function changeStatus(status) {
  if (!workspace.value || !assertionId.value) return
  if (status === 'VERIFIED' && !verificationRef.value) { error.value = '验证成立需要填写脱敏验证引用'; return }
  loading.value = true; error.value = ''
  try {
    await updateAssertionStatus(workspace.value, assertionId.value, status, { verification_ref: verificationRef.value, actor: actor.value, task_id: taskId.value, session_id: sessionId.value })
    await inspect()
  } catch (e) { error.value = e.message }
  loading.value = false
}
</script>

<template>
  <div>
    <h1>Assertion Review / 断言确认</h1>
    <p class="notice">状态操作只改变断言状态，不会修改源码或删除历史证据。</p>
    <div class="controls">
      <input v-model="assertionId" placeholder="assertion_id" @keyup.enter="inspect" />
      <button @click="inspect" :disabled="loading || !assertionId">查看</button>
    </div>
    <DataCard :loading="loading" :error="error">
      <div v-if="data?.found">
        <div class="summary"><b>{{ data.assertion?.subject_id }}</b><span>{{ data.assertion?.predicate }}</span><b>{{ data.assertion?.object_id }}</b></div>
        <p>当前状态：<strong>{{ data.assertion?.status }}</strong>；建议：{{ data.action?.action_type }}</p>
        <div class="controls"><input v-model="verificationRef" placeholder="脱敏 verification_ref（验证时必填）" /><input v-model="actor" placeholder="操作人（可选）" /><input v-model="taskId" placeholder="任务 ID（自动继承）" /><input v-model="sessionId" placeholder="会话 ID（自动继承）" /></div>
        <div class="actions"><button @click="changeStatus('VERIFIED')">验证成立</button><button class="reject" @click="changeStatus('REJECTED')">发现误报</button><button @click="changeStatus('AMBIGUOUS')">需要深度分析</button></div>
        <details><summary>身份归并与完整证据</summary><JsonTree :data="data" label="assertion" :depth="0" /></details>
      </div>
    </DataCard>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 10px; }.notice { color: #566; }.controls { display:flex; gap:8px; margin:12px 0; flex-wrap:wrap; }.controls input { flex:1; min-width:200px; padding:8px; border:1px solid #ccd5e0; border-radius:6px; }.controls button,.actions button { padding:8px 12px; border:0; border-radius:6px; background:#2d6ca2; color:#fff; cursor:pointer; }.actions { display:flex; gap:8px; margin:12px 0; flex-wrap:wrap; }.actions .reject { background:#a23b3b; }.summary { display:flex; gap:8px; flex-wrap:wrap; padding:10px; background:#f4f8fc; border-radius:6px; overflow-wrap:anywhere; }
</style>
