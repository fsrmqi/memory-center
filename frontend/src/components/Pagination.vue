<script setup lang="ts">
const props=defineProps<{page:number;pageSize:number;total:number;pages:number;label:string;busy?:boolean}>()
const emit=defineEmits<{change:[page:number];size:[size:number]}>()
</script>
<template><div class="pagination" :aria-label="label+'分页'"><label>每页<select :value="pageSize" :aria-label="label+'每页条数'" :disabled="busy" @change="emit('size',Number(($event.target as HTMLSelectElement).value))"><option :value="10">10 条</option><option :value="20">20 条</option><option :value="50">50 条</option></select></label><span class="muted">共 {{total}} 条</span><div class="pager-buttons"><button :aria-label="label+'上一页'" @click="emit('change',page-1)" :disabled="page<=1||busy">‹</button><span>第 {{page}} / {{pages}} 页</span><button :aria-label="label+'下一页'" @click="emit('change',page+1)" :disabled="page>=pages||busy">›</button></div></div></template>
