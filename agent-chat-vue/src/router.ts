import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
    history: createWebHistory(),
    routes: [
        // Convenience redirects (legacy / absolute links)
        { path: '/agents', redirect: '/chat/agents' },
        { path: '/custom-agents', redirect: '/chat/custom-agents' },
        { path: '/custom-agents/new', redirect: '/chat/custom-agents/new' },
        { path: '/custom-agents/:id', redirect: (to) => `/chat/custom-agents/${String(to.params.id)}` },

        // Agent Builder Wizard (standalone full-screen pages)
        { path: '/agents/create', redirect: '/agents/create/identity' },
        {
            path: '/agents/create/identity',
            name: 'AgentCreateIdentity',
            component: () => import('./views/agent-builder/CreateAgentIdentity.vue'),
        },
        {
            path: '/agents/create/capabilities',
            name: 'AgentCreateCapabilities',
            component: () => import('./views/agent-builder/CreateAgentCapabilities.vue'),
        },
        {
            path: '/agents/create/knowledge',
            name: 'AgentCreateKnowledge',
            component: () => import('./views/agent-builder/CreateAgentKnowledge.vue'),
        },
        {
            path: '/agents/create/review',
            name: 'AgentCreateReview',
            component: () => import('./views/agent-builder/CreateAgentReview.vue'),
        },
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
        {
            path: '/rag-eval',
            name: 'RagEval',
            component: () => import('./views/RagEval.vue'),
        },
        {
            path: '/rag/datasets',
            name: 'RagDatasets',
            component: () => import('./views/rag/RagDatasets.vue'),
        },
        {
            path: '/rag/benchmarks',
            name: 'RagBenchmarks',
            component: () => import('./views/rag/RagBenchmarks.vue'),
        },
    ],
})

export default router
