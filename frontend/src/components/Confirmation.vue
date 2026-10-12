<script setup lang="ts">
import {nextTick,ref,watch} from 'vue'
import {confirmation,answerConfirmation} from '../confirmation'
const dialog=ref<HTMLDialogElement|null>(null)
watch(confirmation,async value=>{if(value){await nextTick();dialog.value?.showModal()}})
</script>
<template><dialog v-if="confirmation" ref="dialog" class="editor-dialog confirmation-dialog" aria-labelledby="confirmation-title" @cancel.prevent="answerConfirmation(false)"><h2 id="confirmation-title">未保存内容</h2><p>{{confirmation.message}}</p><div class="dialog-actions"><button autofocus @click="answerConfirmation(false)">继续编辑</button><button class="primary" @click="answerConfirmation(true)">{{confirmation.accept}}</button></div></dialog></template>
<style scoped>.confirmation-dialog{max-width:480px}.confirmation-dialog p{line-height:1.8}</style>
