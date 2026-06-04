<script setup>
defineProps({
  title: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
</script>

<template>
  <div class="data-card">
    <div v-if="title" class="card-header">
      <h3>{{ title }}</h3>
    </div>
    <div v-if="loading" class="card-loading">Loading...</div>
    <div v-else-if="error" class="card-error">{{ error }}</div>
    <div v-else class="card-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.data-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}
.card-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}
.card-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
}
.card-body {
  padding: 16px;
}
.card-loading {
  padding: 24px;
  text-align: center;
  color: #888;
}
.card-error {
  padding: 16px;
  color: #dc3545;
  background: #fff5f5;
}
</style>
