import axios from 'axios'

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:18200/api',
    timeout: 300000, // 5 minutes for large model inference
    headers: {
        'Content-Type': 'application/json'
    }
})

// 知识库API
export const knowledgeBaseApi = {
    list: () => api.get('/knowledge-bases'),
    get: (id: number) => api.get(`/knowledge-bases/${id}`),
    create: (data: { name: string; description?: string }) => api.post('/knowledge-bases', data),
    update: (id: number, data: any) => api.put(`/knowledge-bases/${id}`, data),
    delete: (id: number) => api.delete(`/knowledge-bases/${id}`),
    getDocuments: (id: number) => api.get(`/knowledge-bases/${id}/documents`),
}

// 文档API
export const documentApi = {
    upload: (kbId: number, file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        return api.post(`/knowledge-bases/${kbId}/documents/upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    importUrl: (kbId: number, url: string) =>
        api.post(`/knowledge-bases/${kbId}/documents/import-url`, { url, knowledge_base_id: kbId }),
    delete: (docId: number) => api.delete(`/documents/${docId}`),
    getChunks: (docId: number) => api.get(`/documents/${docId}/chunks`),
}

// 聊天API
export const chatApi = {
    send: (query: string, kbId?: number, topK: number = 5) =>
        api.post('/chat', { query, knowledge_base_id: kbId, top_k: topK }),
}

export default api
