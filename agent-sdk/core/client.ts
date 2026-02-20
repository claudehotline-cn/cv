/**
 * Agent SDK - HTTP/SSE Client
 * 
 * 封装后端 API 调用和 SSE 流消费
 */

import { StreamParser } from './stream-parser'
import type { ClientConfig, ResumeOptions, ChatState, StreamCallbacks } from './types'

export interface AgentClientOptions extends ClientConfig, StreamCallbacks { }

/**
 * Agent API 客户端
 */
export class AgentClient {
    private baseUrl: string
    private headers: Record<string, string> | (() => Record<string, string>)
    private debug: boolean
    private parser: StreamParser
    private abortController: AbortController | null = null

    constructor(options: AgentClientOptions) {
        this.baseUrl = options.baseUrl.replace(/\/$/, '')  // 移除尾部斜杠
        this.headers = options.headers || {}
        this.debug = options.debug ?? false

        this.parser = new StreamParser({
            onBlock: options.onBlock,
            onUpdate: options.onUpdate,
            onDone: options.onDone,
            onInterrupt: options.onInterrupt,
            onError: options.onError,
            debug: this.debug
        })
    }

    private log(...args: any[]) {
        if (this.debug) console.log('[AgentClient]', ...args)
    }

    private resolveHeaders(): Record<string, string> {
        const extra = typeof this.headers === 'function' ? this.headers() : this.headers
        return {
            'Content-Type': 'application/json',
            ...extra,
        }
    }

    /**
     * 获取当前解析器状态
     */
    getState(): ChatState {
        return this.parser.getState()
    }

    /**
     * 重置状态
     */
    reset(): void {
        this.parser.reset()
    }

    /**
     * 中止当前请求
     */
    abort(): void {
        if (this.abortController) {
            this.abortController.abort()
            this.abortController = null
            this.parser.end()
            this.log('Stream aborted')
        }
    }

    /**
     * 是否正在请求中
     */
    isActive(): boolean {
        return this.abortController !== null
    }

    /**
     * 处理外部传入的事件
     */
    processEvent(event: any): void {
        this.parser.parse(event)
    }

    /**
     * 发送聊天消息并处理流式响应
     */
    async chat(sessionId: string, message: string): Promise<ChatState> {
        this.log('chat:', { sessionId, message })

        // 中止之前的请求
        this.abort()

        this.parser.reset()
        this.parser.start()
        this.abortController = new AbortController()

        try {
            const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/chat`, {
                method: 'POST',
                headers: this.resolveHeaders(),
                body: JSON.stringify({ message }),
                signal: this.abortController.signal
            })

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

            if (!response.body) {
                throw new Error('Response body is null')
            }

            await this.consumeStream(response.body)
        } catch (error) {
            if ((error as Error).name === 'AbortError') {
                this.log('Request aborted')
            } else {
                this.parser.end()
                throw error
            }
        } finally {
            this.abortController = null
        }

        return this.parser.getState()
    }

    /**
     * 恢复中断的会话
     */
    async resume(sessionId: string, options: ResumeOptions): Promise<ChatState> {
        this.log('resume:', { sessionId, ...options })

        // 中止之前的请求
        this.abort()

        this.parser.reset()
        this.parser.start()
        this.abortController = new AbortController()

        try {
            const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/resume`, {
                method: 'POST',
                headers: this.resolveHeaders(),
                body: JSON.stringify({
                    decision: options.decision,
                    feedback: options.feedback || ''
                }),
                signal: this.abortController.signal
            })

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

            if (!response.body) {
                throw new Error('Response body is null')
            }

            await this.consumeStream(response.body)
        } catch (error) {
            if ((error as Error).name === 'AbortError') {
                this.log('Request aborted')
            } else {
                this.parser.end()
                throw error
            }
        } finally {
            this.abortController = null
        }

        return this.parser.getState()
    }

    /**
     * 消费 SSE 流
     */
    private async consumeStream(body: ReadableStream<Uint8Array>): Promise<void> {
        const reader = body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        try {
            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })

                // 按行分割，保留不完整的最后一行
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''

                for (const line of lines) {
                    this.processLine(line)
                }
            }

            // 处理剩余的 buffer
            if (buffer.trim()) {
                this.processLine(buffer)
            }

            this.parser.end()
        } finally {
            reader.releaseLock()
        }
    }

    /**
     * 处理单行 SSE 数据
     */
    private processLine(line: string): void {
        const trimmed = line.trim()

        // 跳过空行和注释
        if (!trimmed || trimmed.startsWith(':')) return

        // 解析 data: 前缀
        if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6)
            try {
                const data = JSON.parse(jsonStr)
                this.parser.parse(data)
            } catch (e) {
                this.log('Failed to parse JSON:', jsonStr)
            }
        }
    }
}
