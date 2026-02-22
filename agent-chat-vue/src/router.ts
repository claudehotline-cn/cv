import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
    history: createWebHistory(),
    routes: [
        // Convenience redirects (legacy / absolute links)
        { path: '/custom-agents', redirect: '/chat/custom-agents' },
        { path: '/custom-agents/new', redirect: '/chat/custom-agents/new' },
        { path: '/custom-agents/:id', redirect: (to) => `/chat/custom-agents/${String(to.params.id)}` },

        {
            path: '/login',
            name: 'login',
            component: () => import('./views/LoginView.vue'),
            meta: { public: true },
        },
        {
            path: '/agents',
            component: () => import('./views/AgentsView.vue'),
            children: [
                {
                    path: '',
                    name: 'Agents',
                    component: () => import('./views/AgentMarketplace.vue'),
                },
                {
                    path: ':id/versions',
                    name: 'AgentVersions',
                    component: () => import('./views/custom-agents/AgentEdit.vue'),
                },

                // Prompt Management
                {
                    path: 'prompts',
                    name: 'PromptList',
                    component: () => import('./views/prompts/PromptList.vue'),
                },
                {
                    path: 'prompts/:id',
                    name: 'PromptEdit',
                    component: () => import('./views/prompts/PromptEdit.vue'),
                },

                // Agent Builder Wizard (rendered inside Agents layout)
                { path: 'create', redirect: '/agents/create/identity' },
                {
                    path: 'create/identity',
                    name: 'AgentCreateIdentity',
                    component: () => import('./views/agent-builder/CreateAgentIdentity.vue'),
                },
                {
                    path: 'create/capabilities',
                    name: 'AgentCreateCapabilities',
                    component: () => import('./views/agent-builder/CreateAgentCapabilities.vue'),
                },
                {
                    path: 'create/knowledge',
                    name: 'AgentCreateKnowledge',
                    component: () => import('./views/agent-builder/CreateAgentKnowledge.vue'),
                },
                {
                    path: 'create/review',
                    name: 'AgentCreateReview',
                    component: () => import('./views/agent-builder/CreateAgentReview.vue'),
                },
            ],
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
                    redirect: '/agents',
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
            component: () => import('./views/audit/AuditLayout.vue'),
            children: [
                {
                    path: '',
                    name: 'audit',
                    component: () => import('./views/audit/AuditRunsView.vue'),
                },
                {
                    path: 'security',
                    name: 'AuditSecurity',
                    component: () => import('./views/audit/SecurityAuditView.vue'),
                },
                {
                    path: ':requestId',
                    name: 'AuditRunDetail',
                    component: () => import('./views/audit/AuditRunDetailView.vue'),
                },
            ],
        },
        {
            path: '/settings',
            component: () => import('./views/settings/SettingsLayout.vue'),
            children: [
                {
                    path: 'security',
                    name: 'SettingsSecurity',
                    component: () => import('./views/settings/SecurityCenterView.vue'),
                },
                {
                    path: 'tenant',
                    name: 'SettingsTenant',
                    component: () => import('./views/settings/TenantMembersView.vue'),
                },
                {
                    path: 'limits',
                    name: 'SettingsLimits',
                    component: () => import('./views/settings/LimitsQuotaView.vue'),
                },
                {
                    path: 'secrets',
                    name: 'SettingsSecrets',
                    component: () => import('./views/settings/SecretsVaultView.vue'),
                },
                {
                    path: 'api-keys',
                    name: 'SettingsApiKeys',
                    component: () => import('./views/settings/ApiKeysView.vue'),
                },
            ],
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

router.beforeEach(async (to) => {
    const auth = useAuthStore()
    if (!auth.initialized) {
        await auth.bootstrap()
    }

    const isPublic = Boolean(to.meta?.public)
    if (isPublic) {
        if (to.path === '/login' && auth.isAuthenticated) {
            return '/'
        }
        return true
    }

    if (!auth.isAuthenticated) {
        return { path: '/login', query: { redirect: to.fullPath } }
    }

    return true
})

export default router
