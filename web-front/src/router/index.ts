import { createRouter, createWebHashHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/views/Dashboard.vue') },
  { path: '/pipelines', component: () => import('@/views/Pipelines.vue') },
  { path: '/sources', component: () => import('@/views/Sources.vue') },
  { path: '/models', component: () => import('@/views/Models.vue') },
  { path: '/observability', component: () => import('@/views/Observability.vue') },
  { path: '/settings', component: () => import('@/views/Settings.vue') },
  { path: '/about', component: () => import('@/views/About.vue') }
]

const router = createRouter({ history: createWebHashHistory(), routes })
export default router

