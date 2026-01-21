/**
 * Agent SDK - Stream Parser
 * 
 * 框架无关的流式消息解析器
 * 从 useStreamParser.ts 提取核心逻辑
 */

import type { MessageBlock, StreamCallbacks, ChatState, ChartData } from './types'

export interface StreamParserOptions extends StreamCallbacks {
    debug?: boolean
}

/**
 * 流式消息解析器
 * 解析 LangGraph 风格的 SSE 消息流
 */
export class StreamParser {
    private blocks: MessageBlock[] = []
    private isStreaming = false
    private isInterrupted = false
    private interruptData: any = null

    private callbacks: StreamCallbacks
    private debug: boolean

    constructor(options: StreamParserOptions = {}) {
        this.callbacks = {
            onBlock: options.onBlock,
            onDone: options.onDone,
            onInterrupt: options.onInterrupt,
            onError: options.onError
        }
        this.debug = options.debug ?? false
    }

    private log(...args: any[]) {
        if (this.debug) console.log('[StreamParser]', ...args)
    }

    /**
     * 获取当前状态
     */
    getState(): ChatState {
        return {
            blocks: [...this.blocks],
            isStreaming: this.isStreaming,
            isInterrupted: this.isInterrupted,
            interruptData: this.interruptData
        }
    }

    /**
     * 重置解析器状态
     */
    reset(): void {
        this.blocks = []
        this.isStreaming = false
        this.isInterrupted = false
        this.interruptData = null
    }

    /**
     * 开始流式传输
     */
    start(): void {
        this.isStreaming = true
    }

    /**
     * 结束流式传输
     */
    end(): void {
        this.isStreaming = false
        this.callbacks.onDone?.(this.blocks)
    }

    /**
     * 解析 SSE 事件数据
     */
    parse(data: any): void {
        if (!this.isStreaming) {
            this.isStreaming = true
        }

        // 判断格式：数组格式 vs 传统事件格式
        if (Array.isArray(data)) {
            if (data.length < 1) return
            this.handleArrayFormat(data[0], data[1] || {})
        } else {
            const type = data.type || 'unknown'
            this.handleLegacyFormat(type, data)
        }
    }

    /**
     * 添加一个 block 并触发回调
     */
    private addBlock(block: MessageBlock): void {
        this.blocks.push(block)
        this.callbacks.onBlock?.(block)
    }

    /**
     * 从 metadata 中提取 subgraph 名称
     */
    private extractSubgraphName(metadata: any): string | undefined {
        const tags = metadata?.tags || []
        const runName = metadata?.run_name || ''

        for (const tag of tags) {
            if (typeof tag === 'string' && tag.startsWith('agent:')) {
                return tag.replace('agent:', '')
            }
        }
        if (runName) return runName
        return undefined
    }

    /**
     * 处理 [message, metadata] 数组格式 (LangGraph 风格)
     */
    private handleArrayFormat(msg: any, metadata: any): void {
        const subgraphName = this.extractSubgraphName(metadata)
        this.log('Array format:', { type: msg.type, subgraph: subgraphName })

        // 1. 提取 reasoning 内容
        let reasoningDelta = ''
        if (msg.additional_kwargs?.reasoning_content) {
            reasoningDelta = msg.additional_kwargs.reasoning_content
        } else if (Array.isArray(msg.content)) {
            msg.content.forEach((c: any) => {
                if (c.type === 'reasoning' && c.reasoning) {
                    reasoningDelta += c.reasoning
                }
            })
        }

        // 追加 thinking 块
        if (reasoningDelta) {
            const lastBlock = this.blocks[this.blocks.length - 1]
            if (lastBlock && lastBlock.type === 'thinking' && lastBlock.subgraph === subgraphName) {
                lastBlock.content = (lastBlock.content || '') + reasoningDelta
            } else {
                this.addBlock({
                    type: 'thinking',
                    content: reasoningDelta,
                    subgraph: subgraphName
                })
            }
        }

        // 2. 处理 ToolMessage
        if (msg.type === 'tool' || msg.type === 'ToolMessage') {
            const toolContent = typeof msg.content === 'string'
                ? msg.content
                : JSON.stringify(msg.content)

            this.addBlock({
                type: 'tool_output',
                callId: msg.tool_call_id || '',
                output: toolContent,
                subgraph: subgraphName
            })
            return
        }

        // 3. 提取文本内容
        let rawText = ''
        if (typeof msg.content === 'string') {
            rawText = msg.content
        } else if (Array.isArray(msg.content)) {
            msg.content.forEach((c: any) => {
                if (c.type === 'text') rawText += c.text
            })
        }

        // 追加 content 块
        if (rawText) {
            const lastBlock = this.blocks[this.blocks.length - 1]
            if (lastBlock && lastBlock.type === 'content') {
                lastBlock.content = (lastBlock.content || '') + rawText
            } else {
                this.addBlock({
                    type: 'content',
                    content: rawText
                })
            }
        }

        // 4. 处理完整的 tool_calls
        if (msg.tool_calls && msg.tool_calls.length > 0) {
            for (const tc of msg.tool_calls) {
                this.addBlock({
                    type: 'tool_call',
                    call: {
                        id: tc.id || '',
                        name: tc.name || 'unknown',
                        args: tc.args || {}
                    },
                    subgraph: subgraphName
                })
            }
        }

        // 5. 处理中断 (Interrupt)
        if (msg.__interrupt__ || msg.type === 'interrupt') {
            const intData = msg.__interrupt__ || msg.data || msg

            if (this.isInterrupted) return

            this.isInterrupted = true
            this.interruptData = intData
            this.addBlock({
                type: 'interrupt',
                data: intData
            })
            this.callbacks.onInterrupt?.(intData)
        }
    }

    /**
     * 处理传统事件格式
     */
    private handleLegacyFormat(type: string, data: any): void {
        const lastBlock = this.blocks[this.blocks.length - 1]

        switch (type) {
            case 'message_start':
                break

            case 'content':
            case 'content_delta': {
                let textContent = ''
                if (Array.isArray(data.content)) {
                    textContent = data.content
                        .filter((c: any) => c.type === 'text')
                        .map((c: any) => c.text)
                        .join('')
                } else {
                    textContent = data.content || data.delta || ''
                }

                if (lastBlock && lastBlock.type === 'content') {
                    lastBlock.content = (lastBlock.content || '') + textContent
                } else {
                    this.addBlock({ type: 'content', content: textContent })
                }
                break
            }

            case 'thinking_start':
                this.addBlock({ type: 'thinking', content: '', subgraph: undefined })
                break

            case 'thinking':
            case 'thinking_delta': {
                const thinkingContent = data.content || data.delta || ''
                const currentSubgraph = data.subgraph

                if (lastBlock && lastBlock.type === 'thinking' && lastBlock.subgraph === currentSubgraph) {
                    lastBlock.content = (lastBlock.content || '') + thinkingContent
                } else {
                    this.addBlock({
                        type: 'thinking',
                        content: thinkingContent,
                        subgraph: currentSubgraph
                    })
                }
                break
            }

            case 'tool_call':
                if (data.tool) {
                    this.addBlock({
                        type: 'tool_call',
                        call: {
                            id: data.id,
                            name: data.tool,
                            args: data.args || {}
                        },
                        subgraph: data.subgraph
                    })
                }
                break

            case 'tool_output':
                this.addBlock({
                    type: 'tool_output',
                    callId: data.id,
                    output: data.output,
                    subgraph: data.subgraph
                })
                break

            case 'chart':
                this.addBlock({
                    type: 'chart',
                    data: data as ChartData
                })
                break

            case 'interrupt':
                this.isInterrupted = true
                this.interruptData = data
                this.addBlock({
                    type: 'interrupt',
                    data: data
                })
                this.callbacks.onInterrupt?.(data)
                break

            case 'done':
            case 'message_end':
                this.end()
                break

            case 'error':
                console.error('Stream error:', data.message || data.error)
                this.isStreaming = false
                this.callbacks.onError?.(new Error(data.message || data.error || 'Unknown error'))
                break
        }
    }
}
