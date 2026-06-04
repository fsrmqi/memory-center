<script setup>
import { ref, provide } from 'vue'
import AppLayout from './layouts/AppLayout.vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const workspace = ref(localStorage.getItem('mc_workspace') || '')

provide('workspace', workspace)
</script>

<template>
  <AppLayout v-slot="{ workspace: ws }">
    <router-view :workspace="ws" />
  </AppLayout>
</template>
