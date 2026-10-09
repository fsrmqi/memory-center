<script setup lang="ts">
import { onMounted, ref } from 'vue'
type Status = { version: string; ready: boolean; stage: string }
const status = ref<Status | null>(null)
const error = ref('')
const loading = ref(true)
async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/service/status', { signal: AbortSignal.timeout(5000) })
    if (!response.ok) throw new Error('服务暂时无法响应')
    status.value = await response.json()
  } catch { error.value = '无法连接服务，请检查服务状态后重试。' }
  finally { loading.value = false }
}
onMounted(refresh)
</script>
<template>
  <div class="shell">
    <aside><div class="brand">M<span>Memory Center</span></div><div class="nav">服务概览</div><p>项目上下文 · 知识 · 长期记忆</p></aside>
    <main>
      <header><div class="eyebrow">MEMORY CENTER / 5.0</div><span class="badge">{{ status?.stage || "服务" }} · 开发预览</span></header>
      <h1>你的项目记忆，从这里开始</h1><p class="intro">一个独立运行的服务，为不同项目提供持续的上下文。</p>
      <section class="status" aria-live="polite">
        <div><h2>服务状态</h2><p v-if="loading">正在连接服务…</p><p v-else-if="error" class="error">{{ error }}</p><p v-else>{{ status?.ready ? '服务已就绪' : '服务尚未就绪' }} <span class="version">{{ status?.version }}</span></p></div>
        <button @click="refresh" :disabled="loading">{{ loading ? '连接中' : '刷新状态' }}</button>
      </section>
      <section class="empty"><div class="icon">◇</div><h2>多项目登记接口已就绪</h2><p>已支持项目预览、登记、改名、暂停与恢复。<br>当前通过管理 API 使用，完整管理页面将在后续阶段开放。</p><span class="next">下一步：项目授权与 MCP 隔离</span></section>
      <footer>MCP 入口 <code>/mcp</code><span>全新 5.0 数据空间</span></footer>
    </main>
  </div>
</template>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#263149;font-family:system-ui,-apple-system,sans-serif}.shell{display:flex;min-height:100vh}aside{width:250px;background:#fff;border-right:1px solid #e4e8ee;padding:32px 24px}.brand{display:flex;align-items:center;gap:12px;color:#4757b8;font-size:24px;font-weight:700}.brand span{color:#263149;font-size:17px}.nav{margin-top:48px;background:#eef0fc;border-radius:8px;padding:13px 16px;color:#4656b4}aside p{font-size:12px;color:#778198;margin-top:24px;line-height:1.8}main{width:min(1060px,100%);padding:48px 56px}header{display:flex;justify-content:space-between;align-items:center;gap:12px}.eyebrow{font-size:11px;letter-spacing:2px;color:#78839c}.badge{font-size:12px;background:#e9ecf4;padding:7px 12px;border-radius:20px}h1{font-size:30px;margin:36px 0 12px;letter-spacing:-1px}.intro{color:#768095;line-height:1.8;margin-bottom:32px}.status{display:flex;justify-content:space-between;align-items:center;background:#fff;padding:24px 28px;border:1px solid #e2e6ee;border-radius:12px}.status h2{font-size:14px;margin:0 0 12px}.status p{font-size:14px;margin:0;color:#357a61}.version{margin-left:12px;color:#8490a5;font-size:12px}button{background:#fff;border:1px solid #d7ddea;padding:10px 16px;border-radius:7px;color:#45516a;cursor:pointer}button:disabled{opacity:.5}.empty{text-align:center;margin-top:24px;padding:58px 24px;background:#fff;border:1px dashed #d8dfeb;border-radius:12px}.icon{font-size:40px;color:#7887cf}.empty h2{font-size:20px;margin:22px 0 12px}.empty p{color:#7a8497;line-height:1.9;font-size:14px}.next{display:inline-block;margin-top:16px;font-size:12px;color:#5d6caf;background:#f0f2fb;border-radius:6px;padding:9px 14px}footer{display:flex;gap:12px;margin-top:24px;color:#7d889c;font-size:12px}footer span{margin-left:auto}.error{color:#b44646!important}@media(max-width:760px){aside{display:none}main{padding:28px 20px}h1{font-size:25px}header{flex-wrap:wrap}.status{padding:20px;gap:12px}footer{flex-wrap:wrap}}
</style>
