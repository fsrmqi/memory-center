import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'workbench', component: () => import('../views/WorkbenchView.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/continuity', name: 'continuity', component: () => import('../views/ContinuityView.vue') },
  { path: '/task', name: 'task', component: () => import('../views/TaskView.vue') },
  { path: '/timeline', name: 'timeline', component: () => import('../views/TimelineView.vue') },
  { path: '/receipts', name: 'receipts', component: () => import('../views/ReceiptsView.vue') },
  { path: '/usage', name: 'usage', component: () => import('../views/UsageView.vue') },
  { path: '/backend', name: 'backend', component: () => import('../views/BackendView.vue') },
  { path: '/freshness', name: 'freshness', component: () => import('../views/FreshnessView.vue') },
  { path: '/query', name: 'query', component: () => import('../views/QueryView.vue') },
  { path: '/assertion', name: 'assertion', component: () => import('../views/AssertionView.vue') },
  { path: '/impact', name: 'impact', component: () => import('../views/ImpactView.vue') },
  { path: '/group', name: 'group', component: () => import('../views/GroupView.vue') },
  { path: '/audit', name: 'audit', component: () => import('../views/AuditView.vue') },
  { path: '/health', name: 'health', component: () => import('../views/HealthView.vue') },
  { path: '/verification', name: 'verification', component: () => import('../views/VerificationView.vue') },
  { path: '/flow', name: 'flow', component: () => import('../views/FlowView.vue') },
  { path: '/metrics', name: 'metrics', component: () => import('../views/MetricsView.vue') },
  { path: '/onboard', name: 'onboard', component: () => import('../views/OnboardView.vue') },

]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
