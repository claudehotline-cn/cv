import { createRouter, createWebHashHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: 'Dashboard' } },
  { path: '/pipelines', component: () => import('@/views/Pipelines/List.vue'), meta: { title: 'Pipelines' } },
  { path: '/pipelines/editor', component: () => import('@/views/Pipelines/Editor.vue'), meta: { title: 'Pipeline Editor' } },
  { path: '/pipelines/detail/:name', component: () => import('@/views/Pipelines/Detail.vue'), meta: { title: 'Pipeline Detail' } },
  { path: '/analysis', component: () => import('@/views/Pipelines/AnalysisPanel.vue'), meta: { title: 'Pipeline Analysis' } },
  { path: '/pipelines/list', redirect: '/pipelines' },
  { path: '/pipelines/new', redirect: '/pipelines' },
  { path: '/sources', component: () => import('@/views/Sources/List.vue'), meta: { title: 'Sources' } },
  { path: '/sources/preview', component: () => import('@/views/Sources/Preview.vue'), meta: { title: 'Sources Preview' } },
  { path: '/models', component: () => import('@/views/Models.vue'), meta: { title: 'Models' } },
  { path: '/observability', component: () => import('@/views/Observability.vue'), meta: { title: 'Observability' } },
  { path: '/observability/metrics', component: () => import('@/views/Observability/Metrics.vue'), meta: { title: 'Metrics' } },
  { path: '/observability/logs', component: () => import('@/views/Observability/Logs.vue'), meta: { title: 'Logs' } },
  { path: '/observability/events', component: () => import('@/views/Observability/Events.vue'), meta: { title: 'Events' } },
  { path: '/observability/sessions', component: () => import('@/views/Observability/Sessions.vue'), meta: { title: 'Sessions' } },
  { path: '/admin', component: () => import('@/views/Admin.vue'), meta: { title: 'Admin' } },
  { path: '/orchestration', component: () => import('@/views/Orchestration.vue'), meta: { title: 'Orchestration' } },
  { path: '/settings', component: () => import('@/views/Settings.vue'), meta: { title: 'Settings' } },
  { path: '/about', component: () => import('@/views/About.vue'), meta: { title: 'About' } },
  { path: '/:pathMatch(.*)*', component: { template: '<div style="padding:24px"><h2>404 Not Found</h2><p>页面不存在</p></div>' }, meta: { title: '404' } }
]

const router = createRouter({ history: createWebHashHistory(), routes })
router.afterEach((to) => {
  const base = 'AI 视频监控与分析平台'
  document.title = (to.meta as any)?.title ? `${(to.meta as any).title} - ${base}` : base
})
export default router
