<script setup>
import { inject, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const navItems = [
  { path: '/', label: 'Workbench', icon: '🏠' },
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/continuity', label: 'Continuity', icon: '🔗' },
  { path: '/task', label: '记忆空间', icon: 'TS' },
  { path: '/query', label: 'Query', icon: '🔍' },
  { path: '/assertion', label: '断言确认', icon: '✓' },
  { path: '/impact', label: 'Impact', icon: '⚡' },
  { path: '/group', label: 'Group', icon: '🗂️' },
  { path: '/timeline', label: 'Timeline', icon: '⏱️' },
  { path: '/receipts', label: 'Receipts', icon: '📝' },
  { path: '/usage', label: 'Usage', icon: '📈' },
  { path: '/backend', label: 'Backend', icon: '🗄️' },
  { path: '/freshness', label: 'Freshness', icon: '🔄' },
  { path: '/audit', label: 'Audit', icon: '✅' },
  { path: '/health', label: 'Health', icon: '❤️' },
]

const workspace = inject('workspace')

watch(workspace, (v) => {
  localStorage.setItem('mc_workspace', v)
})

function isActive(path) {
  return route.path === path
}
</script>

<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="brand">Memory Center</div>
      <div class="workspace-input">
        <label>Workspace</label>
        <input
          v-model="workspace"
          placeholder="/path/to/workspace.yaml"
          spellcheck="false"
        />
      </div>
      <nav>
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="{ path: item.path, query: workspace ? { workspace } : {} }"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
    </aside>
    <main class="content">
      <slot :workspace="workspace" />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f8f9fa;
  color: #1a1a2e;
}
.sidebar {
  width: 220px;
  background: #1a1a2e;
  color: #e0e0e0;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  overflow-y: auto;
  z-index: 100;
}
.brand {
  font-size: 16px;
  font-weight: 700;
  color: #4fc3f7;
  padding: 4px 0 8px;
  border-bottom: 1px solid #2a2a4a;
}
.workspace-input {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.workspace-input label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #888;
}
.workspace-input input {
  background: #2a2a4a;
  border: 1px solid #3a3a5a;
  color: #e0e0e0;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-family: monospace;
  width: 100%;
  box-sizing: border-box;
}
.workspace-input input:focus {
  outline: none;
  border-color: #4fc3f7;
}
nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  text-decoration: none;
  color: #c0c0c0;
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover {
  background: #2a2a4a;
  color: #fff;
}
.nav-item.active {
  background: #4fc3f7;
  color: #1a1a2e;
  font-weight: 600;
}
.icon {
  font-size: 14px;
  width: 20px;
  text-align: center;
}
.content {
  flex: 1;
  margin-left: 220px;
  padding: 24px;
  min-height: 100vh;
}

@media (max-width: 760px) {
  .app-layout {
    display: block;
  }
  .sidebar {
    position: static;
    width: auto;
    max-height: none;
    border-bottom: 1px solid #2a2a4a;
  }
  nav {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .nav-item {
    min-width: 0;
  }
  .content {
    margin-left: 0;
    padding: 16px;
  }
}
</style>
