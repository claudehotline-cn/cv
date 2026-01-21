/**
 * Agent SDK - HTTP/SSE Client
 * 
 * 封装后端 API 调用和 SSE 流消费
 */

import { StreamParser, type StreamParserOptions } from './stream-parser'
import type { ClientConfig, ResumeOptions, ChatState, StreamCallbacks } from './types'

export interface AgentClientOptions extends ClientConfig, StreamCallbacks { }

/**
 * Agent API 客户端
 */
export class AgentClient {
    private baseUrl: string
    private headers: Record<string, string>
    private debug: boolean
    private parser: StreamParser

    constructor(options: AgentClientOptions) {
        this.baseUrl = options.baseUrl.replace(/\/$/, '')  // 移除尾部斜杠
        this.headers = {
            'Content-Type': 'application/json',
            ...options.headers
        }
        this.debug = options.debug ?? false

        this.parser = new StreamParser({
            onBlock: options.onBlock,
            onDone: options.onDone,
            onInterrupt: options.onInterrupt,
            onError: options.onError,
            debug: this.debug
        })
    }

    private log(...args: any[]) {
        if (this.debug) console.log('[AgentClient]', ...args)
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
     * 发送聊天消息并处理流式响应
     */
    async chat(sessionId: string, message: string): Promise<ChatState> {
        this.log('chat:', { sessionId, message })
        this.parser.reset()
        this.parser.start()

        try {
            const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/chat`, {
                method: 'POST',
                headers: this.headers,
                body: JSON.stringify({ message })
            })

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

            if (!response.body) {
                throw new Error('Response body is null')
            }

            await this.consumeStream(response.body)
        } catch (error) {
            this.parser.end()
            throw error
        }

        return this.parser.getState()
    }

    /**
     * 恢复中断的会话
     */
    async resume(sessionId: string, options: ResumeOptions): Promise<ChatState> {
        this.log('resume:', { sessionId, ...options })

        // 清除中断状态但保留已有 blocks
        const state = this.parser.getState()
        this.parser.reset()
        // 恢复之前的 blocks (可选，取决于业务需求)

        this.parser.start()

        try {
            const response = await fetch(`${this.baseUrl}/sessions/${sessionId}/resume`, {
                method: 'POST',
                headers: this.headers,
                body: JSON.stringify({
                    decision: options.decision,
                    feedback: options.feedback || ''
                })
            })

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

            if (!response.body) {
                throw new Error('Response body is null')
            }

            await this.consumeStream(response.body)
        } catch (error) {
            this.parser.end()
            throw error
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
