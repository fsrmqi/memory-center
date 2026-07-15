<script setup>
import { ref, inject, watch, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { getWorkHealth, getDiscover, getReplayCampaign, getQualityGatesSummary } from '../api/client.js'
import DataCard from '../components/DataCard.vue'
import JsonTree from '../components/JsonTree.vue'

const workspace = inject('workspace')
const health = ref(null)
const discover = ref(null)
const replayCampaign = ref(null)
const gates = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  if (!workspace.value) return
  loading.value = true; error.value = ''
  try {
    ;[health.value, discover.value, replayCampaign.value, gates.value] = await Promise.all([
      getWorkHealth(workspace.value), getDiscover(workspace.value), getReplayCampaign(workspace.value), getQualityGatesSummary(workspace.value),
    ])
  } catch (e) { error.value = e.message }
  loading.value = false
}
onMounted(load); watch(workspace, load)
</script>
<template>
  <div>
    <h1>Health & Discover</h1>
    <DataCard :loading="loading" :error="error">
      <section v-if="gates" class="gate-summary" :class="`gate-${gates.health}`">
        <div class="gate-heading"><h2>Benchmark & Gate Summary</h2><strong>{{ gates.health }}</strong></div>
        <div class="gate-grid">
          <div><span>Benchmark</span><b>{{ gates.benchmark.score }}/100</b><small>{{ gates.benchmark.quality }}</small></div>
          <div><span>Regression alerts</span><b>{{ gates.regression_alerts.total }}</b><small>{{ gates.regression_alerts.critical }} critical, {{ gates.regression_alerts.warning }} warning</small></div>
          <div><span>Replay campaign</span><b>{{ gates.replay_campaign.total_guidance_events }}</b><small>{{ gates.replay_campaign.passed ? 'coverage ready' : `missing: ${gates.replay_campaign.missing_intents.join(', ') || 'events'}` }}</small></div>
          <div><span>Java unresolved</span><b>{{ gates.java_call_resolution.unresolved_rate }}</b><small>{{ gates.java_call_resolution.unresolved_call_edge_count }} / {{ gates.java_call_resolution.call_edge_count }}</small></div>
        </div>
        <ul v-if="gates.benchmark.recommendations?.length" class="gate-recommendations"><li v-for="item in gates.benchmark.recommendations" :key="item">{{ item }}</li></ul>
        <div class="gate-actions"><RouterLink :to="{ path: '/query', query: { mode: 'walkthrough', report_level: 'standard' } }">Open walkthrough review</RouterLink></div>
      </section>
      <div v-if="health" class="section">
        <h3>Work Health</h3>
        <JsonTree :data="health" label="health" :depth="0" />
      </div>
      <div v-if="discover" class="section">
        <h3>Discover</h3>
        <JsonTree :data="discover" label="discover" :depth="0" />
      </div>
      <div v-if="replayCampaign" class="section">
        <h3>Replay Campaign</h3>
        <div class="campaign-state" :class="replayCampaign.passed ? 'passed' : 'pending'">
          {{ replayCampaign.passed ? 'Ready for policy review' : 'More real replay coverage required' }}
        </div>
        <JsonTree :data="replayCampaign.coverage" label="coverage" :depth="0" />
      </div>
    </DataCard>
  </div>
</template>
<style scoped>
h1 { margin: 0 0 16px; }
.section { margin: 16px 0; }
.section h3 { font-size: 14px; margin: 0 0 8px; color: #333; }
.campaign-state { margin-bottom: 8px; font-weight: 600; }
.campaign-state.passed { color: #17733a; }
.campaign-state.pending { color: #9a6700; }
.gate-summary { border: 1px solid #d9e2ef; border-radius: 8px; padding: 14px; margin-bottom: 20px; background: #fff; }
.gate-summary.gate-warning { border-color: #edc66d; }.gate-summary.gate-critical { border-color: #e18b8b; }
.gate-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }.gate-heading h2 { font-size:16px; margin:0; }.gate-heading strong { text-transform:uppercase; font-size:12px; }
.gate-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.gate-grid div { border-left:3px solid #4a6fa5; padding-left:9px; display:flex; flex-direction:column; gap:3px; }.gate-grid span,.gate-grid small { color:#667085; font-size:12px; }.gate-grid b { font-size:18px; }
.gate-recommendations { margin:12px 0 0; padding-left:18px; color:#344054; font-size:13px; }
.gate-actions { margin-top: 12px; }.gate-actions a { display: inline-block; border: 1px solid #4a6fa5; border-radius: 6px; padding: 7px 10px; color: #2d568c; font-size: 12px; font-weight: 600; text-decoration: none; }.gate-actions a:hover { background: #f4f8fd; }
@media (max-width: 700px) { .gate-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
