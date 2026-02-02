/**
 * API 客户端
 */
import axios, { type AxiosInstance } from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

// Dev-only identity headers (temporary until real auth is added)
export const DEV_USER_ID = 'dev_user_001'
export const DEV_USER_ROLE: 'admin' | 'user' = 'admin'

function devHeaders() {
    return {
        'X-User-Id': DEV_USER_ID,
        'X-User-Role': DEV_USER_ROLE,
    }
}

export interface CreateSessionRequest {
    title?: string
}

export interface ChatRequest {
    message: string
    config?: Record<string, unknown>
}

export interface FeedbackRequest {
    decision: 'approve' | 'reject'
    message?: string
}

class ApiClient {
    private baseUrl: string
    public http: AxiosInstance

    constructor(baseUrl: string = API_BASE) {
        this.baseUrl = baseUrl
        this.http = axios.create({
            baseURL: baseUrl,
            headers: {
                'Content-Type': 'application/json',
                ...devHeaders(),
            }
        })

        // interceptors can be added here
        this.http.interceptors.response.use(
            response => response.data,
            error => {
                // handle global errors
                return Promise.reject(error)
            }
        )
    }

    // Agent 操作
    async listAgents(): Promise<any[]> {
        return this.http.get('/agents/')
    }

    async getAgent(agentId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}`)
    }

    async createAgent(config: any): Promise<any> {
        return this.http.post('/agents/', config)
    }

    async updateAgent(agentId: string, config: any): Promise<any> {
        return this.http.put(`/agents/${agentId}`, config)
    }

    async deleteAgent(agentId: string): Promise<void> {
        return this.http.delete(`/agents/${agentId}`)
    }

    async getAgentSchema(agentId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}/config-schema`)
    }

    // Session 操作
    async createSession(title?: string, agentId?: string): Promise<any> {
        return this.http.post('/sessions/', {
            title: title || '新对话',
            agent_id: agentId
        })
    }

    async listSessions(limit = 50): Promise<any> {
        return this.http.get('/sessions/', { params: { limit } })
    }

    async getSession(sessionId: string): Promise<any> {
        return this.http.get(`/sessions/${sessionId}`)
    }

    async deleteSession(sessionId: string): Promise<void> {
        return this.http.delete(`/sessions/${sessionId}`)
    }

    // 流式对话 - Fetch is better for streams
    streamChat(
        sessionId: string,
        message: string,
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...devHeaders() },
                    body: JSON.stringify({ message }),
                    signal: controller.signal,
                })

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('event:')) {
                            // 下一行应该是 data
                            continue
                        }
                        if (line.startsWith('data:')) {
                            try {
                                const data = JSON.parse(line.substring(5).trim())
                                onEvent(data.event || 'unknown', data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()

        return () => controller.abort()
    }

    // HITL Resume - Streaming
    resumeChat(
        sessionId: string,
        request: { decision: string, feedback: string },
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/resume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...devHeaders() },
                    body: JSON.stringify(request),
                    signal: controller.signal,
                })

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`)
                }

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                // SSE data usually array [msg, meta] or simple object {type: ...}
                                // Dispatch as event 'message' or use data.type
                                const eventType = Array.isArray(data) ? 'message' : (data.type || 'unknown')
                                onEvent(eventType, data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()

        return () => controller.abort()
    }

    async getState(sessionId: string): Promise<any> {
        return this.http.get(`/sessions/${sessionId}/state`)
    }

    // Async Task 操作
    async executeTask(sessionId: string, message: string, config?: any): Promise<any> {
        return this.http.post(`/tasks/sessions/${sessionId}/execute`, { message, config })
    }

    async getTask(taskId: string): Promise<any> {
        return this.http.get(`/tasks/${taskId}`)
    }

    async cancelTask(taskId: string): Promise<any> {
        return this.http.post(`/tasks/${taskId}/cancel`)
    }

    async resumeTask(taskId: string, decision: 'approve' | 'reject', feedback: string = ''): Promise<any> {
        return this.http.post(`/tasks/${taskId}/resume`, { decision, feedback })
    }

    async listSessionTasks(sessionId: string, params?: { status?: string; limit?: number }): Promise<any> {
        return this.http.get(`/tasks/sessions/${sessionId}`, { params })
    }

    streamSessionTasks(
        sessionId: string,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/tasks/sessions/${sessionId}/stream`, {
                    headers: devHeaders(),
                    signal: controller.signal,
                })

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                onEvent(data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()
        return () => controller.abort()
    }

    // Audit API
    async listAuditRuns(params: {
        limit?: number;
        offset?: number;
        status?: string;
        agent?: string;
        q?: string;
        start_date?: string;
        end_date?: string;
    } = {}): Promise<{ items: any[], total: number }> {
        return this.http.get('/audit/runs', { params: { limit: 50, ...params } })
    }

    async getAuditRunSummary(runId: string): Promise<any> {
        return this.http.get(`/audit/runs/${runId}/summary`)
    }

    // RAG (via agent-api /rag gateway)
    async listKnowledgeBases(): Promise<{ items: any[] }> {
        return this.http.get('/rag/knowledge-bases')
    }

    async createKnowledgeBase(input: {
        name: string
        description?: string
        chunk_size?: number
        chunk_overlap?: number
        cleaning_rules?: Record<string, any>
    }): Promise<any> {
        return this.http.post('/rag/knowledge-bases', input)
    }

    async getKnowledgeBase(kbId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}`)
    }

    async updateKnowledgeBase(kbId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/knowledge-bases/${kbId}`, patch)
    }

    async deleteKnowledgeBase(kbId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}`)
    }

    async getKnowledgeBaseStats(kbId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/stats`)
    }

    async listKnowledgeBaseDocuments(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents`)
    }

    async deleteKnowledgeBaseDocument(kbId: number, docId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}/documents/${docId}`)
    }

    async uploadKnowledgeBaseDocument(kbId: number, file: File): Promise<any> {
        const form = new FormData()
        form.append('file', file)
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/upload`, form, {
            headers: {
                ...devHeaders(),
                'Content-Type': 'multipart/form-data',
            },
        })
    }

    async importKnowledgeBaseUrl(kbId: number, url: string): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/import-url`, {
            url,
            knowledge_base_id: kbId,
        })
    }

    async reindexDocument(kbId: number, docId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/${docId}/reindex`, {})
    }

    async listDocumentChunks(
        kbId: number,
        docId: number,
        params?: { offset?: number; limit?: number; include_parents?: boolean }
    ): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents/${docId}/chunks`, { params })
    }

    async getDocumentOutline(kbId: number, docId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents/${docId}/outline`)
    }

    async previewDocumentChunks(
        kbId: number,
        docId: number,
        input: { chunk_size?: number; chunk_overlap?: number; cleaning_rules?: Record<string, any>; limit?: number }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/${docId}/preview-chunks`, input)
    }

    async rebuildKnowledgeBaseVectors(kbId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/rebuild-vectors`, {})
    }

    async buildKnowledgeBaseGraph(kbId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/build-graph`, {})
    }

    async ragRetrieve(input: { query: string; knowledge_base_id?: number; top_k?: number }): Promise<any> {
        return this.http.post('/rag/retrieve', input)
    }

    async ragGraphRetrieve(input: { query: string; knowledge_base_id?: number; top_k?: number }): Promise<any> {
        return this.http.post('/rag/graph/retrieve', input)
    }

    async ragEvaluate(input: { question: string; answer: string; contexts?: string[] }): Promise<any> {
        return this.http.post('/rag/evaluate', input)
    }

    // RAG Eval (Datasets / Benchmarks)
    async listEvalDatasets(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets`)
    }

    async createEvalDataset(kbId: number, input: { name: string; description?: string }): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets`, input)
    }

    async updateEvalDataset(kbId: number, datasetId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}`, patch)
    }

    async deleteEvalDataset(kbId: number, datasetId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}`)
    }

    async exportEvalDataset(kbId: number, datasetId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/export`)
    }

    async importEvalDataset(
        kbId: number,
        datasetId: number,
        input: {
            replace?: boolean
            cases: Array<{
                query: string
                expected_sources?: string[]
                expected_answer?: string
                notes?: string
                tags?: string[]
            }>
        }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/import`, input)
    }

    async listEvalCases(kbId: number, datasetId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases`)
    }

    async createEvalCase(
        kbId: number,
        datasetId: number,
        input: { query: string; expected_sources?: string[]; expected_answer?: string; notes?: string; tags?: string[] }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases`, input)
    }

    async bulkDeleteEvalCases(kbId: number, datasetId: number, caseIds: number[]): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases/bulk-delete`, {
            case_ids: caseIds,
        })
    }

    async updateEvalCase(caseId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/eval/cases/${caseId}`, patch)
    }

    async deleteEvalCase(caseId: number): Promise<any> {
        return this.http.delete(`/rag/eval/cases/${caseId}`)
    }

    async createBenchmarkRun(
        kbId: number,
        input: { dataset_id: number; mode: 'vector' | 'graph' | 'qa'; top_k: number }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs`, input)
    }

    async listBenchmarkRuns(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs`)
    }

    async getBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}`)
    }

    async executeBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/execute`, {})
    }

    async listBenchmarkResults(kbId: number, runId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/results`)
    }

    async exportBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/export`)
    }

    streamTask(
        taskId: string,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/tasks/${taskId}/stream`, {
                    headers: devHeaders(),
                    signal: controller.signal,
                })

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                onEvent(data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()
        return () => controller.abort()
    }
}

export const apiClient = new ApiClient()
export default apiClient
