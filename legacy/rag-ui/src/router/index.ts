import { createRouter, createWebHistory } from 'vue-router'

const routes = [
    {
        path: '/',
        redirect: '/knowledge-bases'
    },
    {
        path: '/knowledge-bases',
        name: 'KnowledgeBases',
        component: () => import('../views/KnowledgeBases.vue')
    },
    {
        path: '/knowledge-bases/:id',
        name: 'KnowledgeBaseDetail',
        component: () => import('../views/KnowledgeBaseDetail.vue')
    },
    {
        path: '/chat',
        name: 'Chat',
        component: () => import('../views/Chat.vue')
    },
    {
        path: '/article-agent',
        name: 'ArticleAgent',
        component: () => import('../views/ArticleAgent.vue')
    },
    {
        path: '/data-agent',
        name: 'DataAgent',
        component: () => import('../views/DataAgent.vue')
    },
    {
        path: '/finance-docs',
        name: 'FinanceDocs',
        component: () => import('../views/KnowledgeBase.vue'),
        meta: { layout: 'full' }
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

export default router
