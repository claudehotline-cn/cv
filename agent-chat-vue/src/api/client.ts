/**
 * API 客户端
 */
import axios, { type AxiosInstance } from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

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
                'Content-Type': 'application/json'
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
                    headers: { 'Content-Type': 'application/json' },
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
                    headers: { 'Content-Type': 'application/json' },
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

    streamTask(
        taskId: string,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/tasks/${taskId}/stream`, {
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
