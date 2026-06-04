<script setup>
import { ref } from 'vue'

const props = defineProps({
  data: { type: [Object, Array], default: null },
  label: { type: String, default: 'root' },
  depth: { type: Number, default: 0 },
})

const expanded = ref(props.depth < 2)

function isObject(v) {
  return v !== null && typeof v === 'object'
}

function format(v) {
  if (v === null) return 'null'
  if (typeof v === 'string') return `"${v.length > 120 ? v.slice(0, 120) + '...' : v}"`
  return String(v)
}
</script>

<template>
  <div class="json-tree" :style="{ paddingLeft: depth * 16 + 'px' }">
    <span v-if="isObject(data)" class="toggle" @click="expanded = !expanded">
      {{ expanded ? '▼' : '▶' }} {{ label }}
      <span class="count">({{ Array.isArray(data) ? data.length : Object.keys(data).length }})</span>
    </span>
    <span v-else>
      <span class="key-label">{{ label }}:</span> <span class="val">{{ format(data) }}</span>
    </span>
    <div v-if="expanded && isObject(data)">
      <template v-if="Array.isArray(data)">
        <JsonTree v-for="(item, i) in data.slice(0, 50)" :key="i" :data="item" :label="String(i)" :depth="depth + 1" />
        <div v-if="data.length > 50" class="more" :style="{ paddingLeft: (depth + 1) * 16 + 'px' }">
          ... {{ data.length - 50 }} more
        </div>
      </template>
      <template v-else>
        <JsonTree v-for="(val, key) in data" :key="key" :data="val" :label="key" :depth="depth + 1" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.json-tree {
  font-size: 12px;
  font-family: 'SF Mono', 'Menlo', monospace;
  line-height: 1.6;
}
.toggle {
  cursor: pointer;
  user-select: none;
  color: #4a6fa5;
}
.toggle:hover {
  text-decoration: underline;
}
.count {
  color: #999;
  font-size: 11px;
}
.key-label {
  color: #881391;
}
.val {
  color: #1a1a2e;
}
.more {
  color: #999;
  font-style: italic;
}
</style>
