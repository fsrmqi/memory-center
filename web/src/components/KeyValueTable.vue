<script setup>
defineProps({
  data: { type: Object, default: () => ({}) },
})
</script>

<template>
  <table class="kv-table" v-if="data && Object.keys(data).length">
    <tr v-for="(value, key) in data" :key="key">
      <td class="key">{{ key }}</td>
      <td class="value">
        <template v-if="typeof value === 'object' && value !== null">
          <pre class="json-pre">{{ JSON.stringify(value, null, 2) }}</pre>
        </template>
        <template v-else>{{ value }}</template>
      </td>
    </tr>
  </table>
  <div v-else class="empty">No data</div>
</template>

<style scoped>
.kv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.kv-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: top;
}
.key {
  font-weight: 600;
  color: #555;
  white-space: nowrap;
  width: 180px;
}
.value {
  color: #1a1a2e;
  word-break: break-all;
}
.json-pre {
  margin: 0;
  font-size: 11px;
  background: #f5f5f5;
  padding: 6px;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 200px;
}
.empty {
  color: #999;
  padding: 8px;
}
</style>
