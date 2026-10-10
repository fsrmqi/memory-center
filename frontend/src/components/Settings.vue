<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { action, api, type Workspace, type Item } from '../api'

import Pagination from './Pagination.vue'
import { usePagination } from '../pagination'
const serverOrigin = location.origin
const localHttp = JSON.stringify({ mcpServers: { 'memory-center': { url: serverOrigin + '/mcp' } } }, null, 2)
const localStdio = JSON.stringify({ mcpServers: { 'memory-center': { command: 'memory-center-mcp', env: { MEMORY_CENTER_URL: serverOrigin + '/mcp' } } } }, null, 2)

const props = defineProps<{ section: 'models' | 'credentials'; workspaces: Workspace[]; local?: boolean }>()

const settings = ref({ url: '', model: '', protocol: 'ollama', dimensions: 1024 })
const chat = ref({url:'',model:'',protocol:'ollama',max_tokens:4096})
const jobSettings = ref({max_projects:1,max_queued:0,max_file_workers:0})
const backend = ref('')
const runtime = ref<any>(null)
const items = ref<Item[]>([])
const pager=usePagination(()=>items.value)
const selected = ref<string[]>([])
const name = ref('')
const writable = ref(false)
const issued = ref<any>(null)
const busy = ref(false)

onMounted(() => action(async () => {
  const value = await api('/models')
  backend.value = value.backend
  const [c,j] = await Promise.all([api('/chat-model'),api('/job-settings')])
  if(c.items[0])chat.value={url:c.items[0].url,model:c.items[0].model,protocol:c.items[0].protocol,max_tokens:c.items[0].max_tokens}
  jobSettings.value={max_projects:j.max_projects,max_queued:j.max_queued,max_file_workers:j.max_file_workers??0}
  if (value.items[0]) {
    const m = value.items[0]
    settings.value = { url: m.url, model: m.model, protocol: m.protocol, dimensions: m.dimensions }
  }
  // 后端能力边界与索引上限必须显式可见，避免切换部署形态时能力静默降级。
  try { runtime.value = await api('/service/status') } catch { runtime.value = null }
  if (!props.local) items.value = (await api('/credentials')).items
}, '设置已加载'))

async function save() { await action(async () => { await api('/models', 'PUT', settings.value) }, '模型已保存，已有项目需重新索引') }
async function test() { busy.value = true; await action(async () => { await api('/models/test', 'POST', settings.value) }, '模型连接与向量维度验证通过'); busy.value = false }
async function saveChat(){await action(async()=>{await api('/chat-model','PUT',chat.value)},'普通模型已保存，无需重新索引')}
async function testChat(){busy.value=true;await action(async()=>{await api('/chat-model/test','POST',chat.value)},'普通模型连接验证通过');busy.value=false}
async function saveJobs(){await action(async()=>{await api('/job-settings','PUT',jobSettings.value)},'并发设置已生效；已有任务继续执行')}
async function issue() { await action(async () => { issued.value = await api('/credentials', 'POST', { name: name.value, workspace_ids: selected.value, writable: writable.value }); items.value = (await api('/credentials')).items }, '凭据已创建，请保存一次性令牌') }
async function revoke(item: Item) { await action(async () => { await api('/credentials/' + item.id, 'DELETE'); items.value = (await api('/credentials')).items }, '凭据已撤销') }
function connection() { return JSON.stringify({ mcpServers: { 'memory-center': { url: serverOrigin + '/mcp', headers: { Authorization: 'Bearer ' + issued.value.token } } } }, null, 2) }
</script>

<template>
  <template v-if="section === 'models'">
    <div class="page-title">
      <div>
        <h1>模型设置</h1>
        <p>分别配置检索向量模型与用于整理 Wiki、记忆的普通模型。</p>
      </div>
      <span class="state">{{ backend === 'postgresql' ? 'PostgreSQL + pgvector' : 'SQLite 轻量存储' }}</span>
    </div>

    <section class="form-panel">
      <form @submit.prevent="save">
        <h2>向量模型</h2>
        <label>嵌入协议
          <select v-model="settings.protocol">
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI-compatible</option>
          </select>
        </label>
        <label>服务地址<input v-model="settings.url" placeholder="例如 http://host.docker.internal:11434"></label>
        <label>模型名称<input v-model="settings.model" placeholder="填写已安装模型的名称"></label>
        <label>向量维度<input type="number" v-model.number="settings.dimensions" min="1" max="4096"></label>
        <p class="muted">不填写模型时只启用关键词与代码事实检索。模型需预先安装；远程模型会接收待嵌入文本。密钥由服务环境变量 MEMORY_CENTER_MODEL_API_KEY 提供，不在页面保存。</p>
        <div class="actions">
          <button type="button" @click="test" :disabled="busy">{{ busy ? '正在验证…' : '验证连接' }}</button>
          <button class="primary">保存模型</button>
        </div>
      </form>
    </section>

    <section class="form-panel"><form @submit.prevent="saveChat"><h2>普通模型 · 智能整理</h2>
      <label>模型协议<select v-model="chat.protocol"><option value="ollama">Ollama</option><option value="openai">OpenAI-compatible</option></select></label>
      <label>服务地址<input v-model="chat.url" placeholder="Ollama 根地址，或 OpenAI-compatible 的 /v1 地址"></label>
      <label>模型名称<input v-model="chat.model" placeholder="填写可用于对话的模型名称"></label>
      <label>最大输出 Token<input type="number" v-model.number="chat.max_tokens" min="256" max="32768"></label>
      <p class="muted">用于整理已保存的 Wiki 和记忆；结果先预览，再确认保存。远程模型会收到你选中的正文。密钥通过服务环境变量 MEMORY_CENTER_CHAT_API_KEY 提供。</p>
      <div class="actions"><button type="button" @click="testChat" :disabled="busy">{{busy?'正在验证…':'验证普通模型'}}</button><button class="primary" :disabled="busy">保存普通模型</button></div>
    </form></section>
    <section class="form-panel"><form @submit.prevent="saveJobs"><h2>后台任务并发</h2>
      <label>同时索引的项目数<input type="number" v-model.number="jobSettings.max_projects" min="1" max="64"></label>
      <label>排队任务上限<input type="number" v-model.number="jobSettings.max_queued" min="0" max="100000"></label>
      <label>每项目解析进程数<input type="number" v-model.number="jobSettings.max_file_workers" min="0" max="64"></label>
      <p class="muted">默认按运行环境 CPU 自动选择项目并发，排队上限 0 表示不限。每项目解析进程数 0 表示在同时运行的项目之间自动切分同一份 CPU 预算（项目进程本身占一个槽位），填正数则按每项目固定宽度执行。降低并发不终止现有任务，新任务按新配置调度。</p>
      <button class="primary">保存并发设置</button>
    </form></section>
    <section class="form-panel" v-if="runtime">
      <h2>运行环境</h2>
      <p class="muted">版本 {{ runtime.version }}（{{ runtime.stage === 'stable' ? '正式版' : '开发测试版' }}）。同一数据目录同时只允许一个服务实例，重复启动会在就绪前被拒绝。</p>
      <p class="muted">存储后端：{{ runtime.storage.backend === 'postgresql' ? 'PostgreSQL + pgvector' : 'SQLite 轻量模式' }}。{{ runtime.storage.note }}</p>
      <p class="muted">索引软上限：文件 {{ runtime.index_limits.max_files || '不限' }} 个 / 累计 {{ runtime.index_limits.max_total_mib || '不限' }} MiB / 单文件 {{ runtime.index_limits.max_file_mib || '不限' }} MiB。{{ runtime.index_limits.allow_large_index ? '当前已允许超限索引。' : '默认不限制；显式配置上限后超限会失败，可设置 MEMORY_CENTER_ALLOW_LARGE_INDEX=1 后重新索引。' }}</p>
      <p class="muted">索引内存上限 {{ runtime.index_limits.memory_limit_mib ? runtime.index_limits.memory_limit_mib + ' MiB' : '未设置' }}；索引超时 {{ runtime.index_limits.timeout_seconds ? runtime.index_limits.timeout_seconds + ' 秒' : '未设置' }}。</p>
    </section>
  </template>

  <template v-else-if="local">
    <div class="page-title">
      <div>
        <h1>MCP 接入</h1>
        <p>本机免认证：所有已接入项目与全部工具均可使用。</p>
      </div>
    </div>
    <section class="form-panel">
      <h2>HTTP 连接配置</h2>
      <textarea readonly rows="7" aria-label="MCP 连接配置" :value="localHttp"></textarea>
      <p class="muted">无需令牌、项目授权或读写权限配置。调用时通过 workspace_id 指定项目，避免记忆混用。</p>
      <h2>stdio 客户端</h2>
      <pre>{{ localStdio }}</pre>
    </section>
  </template>

  <template v-else>
    <div class="page-title">
      <div>
        <h1>MCP 接入</h1>
        <p>分配项目范围与读写权限，凭据可随时撤销。</p>
      </div>
    </div>
    <section class="form-panel">
      <form @submit.prevent="issue">
        <label>凭据名称<input v-model="name" required maxlength="120"></label>
        <fieldset>
          <legend>允许访问的项目</legend>
          <label v-for="workspace in workspaces" :key="workspace.workspace_id" class="check">
            <input v-model="selected" :value="workspace.workspace_id" type="checkbox">{{ workspace.name }}
          </label>
        </fieldset>
        <label class="check"><input type="checkbox" v-model="writable">允许会话、记忆、Wiki 写入与索引任务</label>
        <button class="primary" :disabled="!selected.length">创建凭据</button>
      </form>
      <section v-if="issued" class="issued">
        <h2>一次性连接配置</h2>
        <p>关闭页面前保存到客户端私有配置。</p>
        <textarea readonly rows="9" :value="connection()" aria-label="MCP 连接配置"></textarea>
        <button @click="issued = null">隐藏令牌</button>
      </section>
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>名称</th><th>项目范围</th><th>权限</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in pager.rows.value" :key="item.id">
            <td>{{ item.name }}</td>
            <td>{{ item.workspace_ids.map((id: string) => workspaces.find(w => w.workspace_id === id)?.name || id).join('、') }}</td>
            <td>{{ item.writable ? '读写' : '只读' }}</td>
            <td>{{ item.revoked ? '已撤销' : '有效' }}</td>
            <td><button class="danger" v-if="!item.revoked" @click="revoke(item)">撤销</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pagination :page="pager.page.value" :page-size="pager.pageSize.value" :total="pager.total.value" :pages="pager.pages.value" label="MCP 凭据" @change="pager.page.value=$event" @size="pager.pageSize.value=$event;pager.reset()"/>
  </template>
</template>
