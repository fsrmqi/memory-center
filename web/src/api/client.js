import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.error || error.message
    return Promise.reject(new Error(message))
  }
)

export function getHealth() {
  return api.get('/health')
}

export function getWorkspaceStatus(workspace) {
  return api.get('/workspace/status', { params: { workspace } })
}

export function getWorkspaceDashboard(workspace, params = {}) {
  return api.get('/workspace/dashboard', { params: { workspace, ...params } })
}

export function getWorkspaceSniff(workspace, intent, params = {}) {
  return api.get('/workspace/sniff', { params: { workspace, intent, ...params } })
}

export function getContinuityDashboard(workspace, params = {}) {
  return api.get('/workspace/continuity-dashboard', { params: { workspace, ...params } })
}

export function getTimeline(workspace, params = {}) {
  return api.get('/workspace/timeline', { params: { workspace, ...params } })
}

export function getReceipts(workspace, params = {}) {
  return api.get('/workspace/write-receipts', { params: { workspace, ...params } })
}

export function getUsageReport(workspace, params = {}) {
  return api.get('/workspace/tool-usage-report', { params: { workspace, ...params } })
}

export function getBackendQuery(workspace, params = {}) {
  return api.get('/workspace/memory-backend-query', { params: { workspace, ...params } })
}

export function getEvalIndexFreshness(workspace) {
  return api.get('/workspace/eval-index-freshness', { params: { workspace } })
}

export function getBenchmarkTrend(workspace, params = {}) {
  return api.get('/workspace/eval-token-benchmark-trend', { params: { workspace, ...params } })
}

export function getAudit(workspace, params = {}) {
  return api.get('/workspace/audit', { params: { workspace, ...params } })
}

export function getDiscover(workspace, params = {}) {
  return api.get('/workspace/discover', { params: { workspace, ...params } })
}

export function getBackendConsistency(workspace) {
  return api.get('/workspace/backend-consistency', { params: { workspace } })
}

export function queryWorkspace(workspace, text, params = {}) {
  return api.get('/workspace/query', { params: { workspace, text, ...params } })
}

export function searchCode(workspace, query, params = {}) {
  return api.get('/workspace/search-code', { params: { workspace, query, ...params } })
}

export function getSymbol(workspace, name, params = {}) {
  return api.get('/workspace/symbol', { params: { workspace, name, ...params } })
}

export function getCallers(workspace, name, params = {}) {
  return api.get('/workspace/callers', { params: { workspace, name, ...params } })
}

export function getCallees(workspace, name, params = {}) {
  return api.get('/workspace/callees', { params: { workspace, name, ...params } })
}

export function getGroupStatus(group) {
  return api.get('/group/status', { params: { group } })
}

export function groupQuery(group, query, params = {}) {
  return api.get('/group/query', { params: { group, query, ...params } })
}

export function groupImpact(group, target, params = {}) {
  return api.get('/group/impact', { params: { group, target, ...params } })
}

export function getDrillRef(workspace, refId) {
  return api.get('/workspace/drill-ref', { params: { workspace, ref_id: refId } })
}

export function getDrillTimeline(workspace, params = {}) {
  return api.get('/workspace/drill-timeline', { params: { workspace, ...params } })
}

export function getDrillTask(workspace, taskId) {
  return api.get('/workspace/drill-task', { params: { workspace, task_id: taskId } })
}

export function listArtifacts(workspace) {
  return api.get('/workspace/artifacts', { params: { workspace } })
}

export function listTaskSpaces(workspace) {
  return api.get('/workspace/task-spaces', { params: { workspace } })
}

export function getResumePacket(workspace, params = {}) {
  return api.get('/workspace/resume-packet', { params: { workspace, ...params } })
}

export function getNextActions(workspace, params = {}) {
  return api.get('/workspace/next-actions', { params: { workspace, ...params } })
}

export function getHandoffHistory(workspace, params = {}) {
  return api.get('/workspace/handoff-history', { params: { workspace, ...params } })
}

export function getWorkHealth(workspace) {
  return api.get('/workspace/work-health', { params: { workspace } })
}

export function getVerificationLoop(workspace, params = {}) {
  return api.get('/workspace/verification-loop', { params: { workspace, ...params } })
}

export function getPatternPromotion(workspace, params = {}) {
  return api.get('/workspace/pattern-promotion', { params: { workspace, ...params } })
}

export function getHeuristics(workspace, params = {}) {
  return api.get('/workspace/heuristics', { params: { workspace, ...params } })
}

export function getWorkflowProfile(profile) {
  return api.get('/workspace/workflow-profile', { params: { profile } })
}

export function getWorkflowRecommend(description) {
  return api.get('/workspace/workflow-recommend', { params: { description } })
}

export function getBundleExport(workspace, params = {}) {
  return api.get('/workspace/bundle-export', { params: { workspace, ...params } })
}

export function getRuntimeAudit(workspace) {
  return api.get('/workspace/runtime-audit', { params: { workspace } })
}

export function getExplanation(text, persona) {
  return api.get('/workspace/explanation', { params: { text, persona } })
}

export function getBusinessFlow(workspace, seed, params = {}) {
  return api.get('/workspace/business-flow', { params: { workspace, seed, ...params } })
}

export function getBusinessFlowImpact(workspace, nodeId, params = {}) {
  return api.get('/workspace/business-flow-impact', { params: { workspace, node_id: nodeId, ...params } })
}

export function getMetricsSummary() {
  return api.get('/workspace/metrics-summary')
}

export function getRegressionAlerts(workspace, params = {}) {
  return api.get('/workspace/regression-alerts', { params: { workspace, ...params } })
}

export function getOnboard(workspace, params = {}) {
  return api.get('/workspace/onboard', { params: { workspace, ...params } })
}

export function getContextPack(workspace, params = {}) {
  return api.get('/workspace/context-pack', { params: { workspace, ...params } })
}

export function getFreshness(workspace) {
  return api.get('/workspace/freshness', { params: { workspace } })
}

export function getGroupQueryWS(workspace, query, params = {}) {
  return api.get('/workspace/group-query', { params: { workspace, query, ...params } })
}

export function getGroupImpactWS(workspace, target, params = {}) {
  return api.get('/workspace/group-impact', { params: { workspace, target, ...params } })
}

export function getGroupChainWS(workspace, symbol, params = {}) {
  return api.get('/workspace/group-chain', { params: { workspace, symbol, ...params } })
}
