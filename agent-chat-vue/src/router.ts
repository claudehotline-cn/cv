import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
    history: createWebHistory(),
    routes: [
        {
            path: '/',
            name: 'dashboard',
            component: () => import('./views/DashboardView.vue'),
        },
        {
            path: '/chat',
            component: () => import('./components/layout/MainLayout.vue'),
            children: [
                {
                    path: '',
                    name: 'chat',
                    component: () => import('./views/ChatView.vue'),
                },
                {
                    path: 'agents',
                    name: 'agent-marketplace',
                    component: () => import('./views/AgentMarketplace.vue'),
                },
                {
                    path: 'custom-agents',
                    name: 'agent-list',
                    component: () => import('./views/custom-agents/AgentList.vue'),
                },
                {
                    path: 'custom-agents/new',
                    name: 'agent-create',
                    component: () => import('./views/custom-agents/AgentEdit.vue'),
                },
                {
                    path: 'custom-agents/:id',
                    name: 'agent-edit',
                    component: () => import('./views/custom-agents/AgentEdit.vue'),
                },
            ]
        },
        {
            path: '/audit',
            name: 'audit',
            component: () => import('./views/AuditView.vue'),
        },
        {
            path: '/finance-docs',
            name: 'FinanceDocs',
            component: () => import('./views/KnowledgeBase.vue'),
        },
        {
            path: '/document-editor',
            name: 'DocumentEditor',
            component: () => import('./views/DocumentEditor.vue'),
        },
    ],
})

export default router
