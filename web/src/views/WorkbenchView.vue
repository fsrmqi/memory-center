<script setup>
import { ref, inject, onMounted } from 'vue'
import { getHealth } from '../api/client.js'
import DataCard from '../components/DataCard.vue'

const workspace = inject('workspace')
const health = ref(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    health.value = await getHealth()
  } catch (e) {
    health.value = { error: e.message }
  }
  loading.value = false
})

const quickLinks = [
  { path: '/dashboard', label: 'Dashboard', desc: 'Workspace overview and focus task', icon: '📊' },
  { path: '/query', label: 'Query', desc: 'Search code, symbols, and knowledge', icon: '🔍' },
  { path: '/impact', label: 'Impact Analysis', desc: 'Analyze change impact before editing', icon: '⚡' },
  { path: '/group', label: 'Cross-Project', desc: 'Group queries, impact, and chain stitching', icon: '🗂️' },
  { path: '/timeline', label: 'Timeline', desc: 'Session events and write receipts', icon: '⏱️' },
  { path: '/freshness', label: 'Freshness', desc: 'Index staleness and reindex status', icon: '🔄' },
  { path: '/audit', label: 'Audit', desc: 'Documentation and completion audit', icon: '✅' },
  { path: '/health', label: 'Health', desc: 'System health and regression suite', icon: '❤️' },
  { path: '/verification', label: 'Verification', desc: 'Verification loop, workflow profiles, runtime audit', icon: '🔒' },
  { path: '/flow', label: 'Business Flow', desc: 'Extract and trace business flows', icon: '🔀' },
  { path: '/metrics', label: 'Metrics', desc: 'Structured metrics and performance', icon: '📈' },
  { path: '/onboard', label: 'Onboard', desc: 'Guided architecture tour', icon: '🗺️' },

]
</script>

<template>
  <div class="workbench">
    <h1>Memory Center Workbench</h1>
    <p class="subtitle">MCP-native project memory for AI coding agents</p>

    <DataCard title="Connection" :loading="loading">
      <div v-if="health?.ok" class="status-ok">✓ Connected to Memory Center HTTP server</div>
      <div v-else class="status-err">✗ Not connected. Start with: <code>memory-center serve-http</code></div>
    </DataCard>

    <div class="grid">
      <router-link
        v-for="link in quickLinks"
        :key="link.path"
        :to="{ path: link.path, query: workspace ? { workspace } : {} }"
        class="quick-card"
      >
        <div class="qc-icon">{{ link.icon }}</div>
        <div class="qc-label">{{ link.label }}</div>
        <div class="qc-desc">{{ link.desc }}</div>
      </router-link>
    </div>
  </div>
</template>

<style scoped>
.workbench { max-width: 900px; }
h1 { margin: 0 0 4px; font-size: 24px; }
.subtitle { color: #666; margin: 0 0 24px; }
.status-ok { color: #28a745; font-weight: 600; }
.status-err { color: #dc3545; }
.status-err code { background: #f5f5f5; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 20px;
}
.quick-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.quick-card:hover {
  border-color: #4fc3f7;
  box-shadow: 0 2px 8px rgba(79, 195, 247, 0.15);
}
.qc-icon { font-size: 24px; margin-bottom: 8px; }
.qc-label { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.qc-desc { font-size: 12px; color: #888; }
</style>
