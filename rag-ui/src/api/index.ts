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
    buildGraph: (id: number) => api.post(`/knowledge-bases/${id}/build-graph`),
    rebuildVectors: (id: number) => api.post(`/knowledge-bases/${id}/rebuild-vectors`),
    getStats: (id: number) => api.get(`/knowledge-bases/${id}/stats`),
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
    getImages: (docId: number) => api.get(`/documents/${docId}/images`),
}

// 聊天API
export const chatApi = {
    send: (query: string, kbId?: number, topK: number = 5) =>
        api.post('/chat', { query, knowledge_base_id: kbId, top_k: topK }),
    graphRetrieve: (query: string, kbId?: number, depth: number = 2) =>
        api.post('/graph/retrieve', { query, knowledge_base_id: kbId, depth }),
    evaluate: (question: string, answer: string, contexts?: string[]) =>
        api.post('/evaluate', { question, answer, contexts: contexts || [] }),
}

// 多模态API
export const multimodalApi = {
    // 上传媒体文件
    uploadImage: (file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        return api.post('/upload-image', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    uploadAudio: (file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        return api.post('/upload-audio', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    uploadVideo: (file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        return api.post('/upload-video', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    // 多模态查询 (支持文本+图片)
    multimodalQuery: (query: string, imageDesc: string) => {
        return api.post('/multimodal-query', {
            text_query: query,
            image_description: imageDesc
        })
    },
    // 语音查询 (直接上传音频文件提问)
    voiceQuery: (audioFile: File) => {
        const formData = new FormData()
        formData.append('file', audioFile)
        return api.post('/voice-query', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    // 独立图表分析
    analyzeChart: (file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        return api.post('/analyze-chart', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
    },
    // 生成报告
    generateReport: (query: string, reportType: string = 'markdown') => {
        return api.post('/generate-report', {
            query,
            report_type: reportType
        })
    }
}

export default api
