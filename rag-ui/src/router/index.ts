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
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

export default router
