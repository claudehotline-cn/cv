/**
 * API 客户端
 */
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

    constructor(baseUrl: string = API_BASE) {
        this.baseUrl = baseUrl
    }

    // Session 操作
    async createSession(title?: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title || '新对话' }),
        })
        return response.json()
    }

    async listSessions(limit = 50): Promise<any> {
        const response = await fetch(`${this.baseUrl}/sessions?limit=${limit}`)
        return response.json()
    }

    async getSession(sessionId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/sessions/${sessionId}`)
        return response.json()
    }

    async deleteSession(sessionId: string): Promise<void> {
        await fetch(`${this.baseUrl}/sessions/${sessionId}`, { method: 'DELETE' })
    }

    // 流式对话
    streamChat(
        sessionId: string,
        message: string,
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/stream`, {
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
                            const eventType = line.substring(6).trim()
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

    // HITL 反馈
    streamFeedback(
        sessionId: string,
        feedback: FeedbackRequest,
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/feedback`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(feedback),
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

    async getState(sessionId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/state`)
        return response.json()
    }
}

export const apiClient = new ApiClient()
export default apiClient
