/**
 * Stream Parser Composable
 * 
 * 可复用的 SSE 流解析模块，用于处理 LangGraph 消息流。
 * 支持 [message, metadata] 数组格式和传统事件格式。
 */
import { ref, type Ref } from 'vue'
import type { MessageBlock, ChartData } from '@/types'

export interface StreamParserOptions {
    /** 流结束时的回调 */
    onDone?: (blocks: MessageBlock[]) => void
    /** 错误时的回调 */
    onError?: (error: string) => void
    /** 中断时的回调 */
    onInterrupt?: (data: any) => void
    /** 是否启用调试日志 */
    debug?: boolean
}

export interface StreamParserResult {
    /** 当前流式块列表 */
    blocks: Ref<MessageBlock[]>
    /** 是否正在流式传输 */
    isStreaming: Ref<boolean>
    /** 是否被中断 */
    isInterrupted: Ref<boolean>
    /** 中断数据 */
    interruptData: Ref<any>
    /** 处理 SSE 事件 */
    handleEvent: (eventType: string, data: any) => void
    /** 处理错误 */
    handleError: (error: Error) => void
    /** 重置状态 */
    reset: () => void
}

/**
 * 创建一个 stream 解析器实例
 */
export function useStreamParser(options: StreamParserOptions = {}): StreamParserResult {
    const { onDone, onError, onInterrupt, debug = false } = options

    // 响应式状态
    const blocks = ref<MessageBlock[]>([])
    const isStreaming = ref(false)
    const isInterrupted = ref(false)
    const interruptData = ref<any>(null)

    const log = (...args: any[]) => {
        if (debug) console.log('[StreamParser]', ...args)
    }

    /**
     * 从 metadata 中提取 subgraph 名称
     */
    function extractSubgraphName(metadata: any): string | undefined {
        const tags = metadata?.tags || []
        const runName = metadata?.run_name || ''

        // 优先从 tags 中提取 agent:xxx
        for (const tag of tags) {
            if (typeof tag === 'string' && tag.startsWith('agent:')) {
                return tag.replace('agent:', '')
            }
        }
        // 其次使用 run_name
        if (runName) return runName
        return undefined
    }

    /**
     * 处理 [message, metadata] 数组格式（LangGraph 风格）
     */
    function handleArrayFormat(msg: any, metadata: any) {
        const subgraphName = extractSubgraphName(metadata)
        log('Array format:', { type: msg.type, subgraph: subgraphName })

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
            const lastBlock = blocks.value[blocks.value.length - 1]
            if (lastBlock && lastBlock.type === 'thinking' && lastBlock.subgraph === subgraphName) {
                lastBlock.content += reasoningDelta
            } else {
                blocks.value.push({
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


            blocks.value.push({
                type: 'tool_output',
                callId: msg.tool_call_id || '',
                output: toolContent,
                subgraph: subgraphName
            })
            return  // 重要：直接返回，不处理 content
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
            const lastBlock = blocks.value[blocks.value.length - 1]
            if (lastBlock && lastBlock.type === 'content') {
                lastBlock.content += rawText
            } else {
                blocks.value.push({
                    type: 'content',
                    content: rawText
                })
            }
        }

        // 4. 处理完整的 tool_calls
        if (msg.tool_calls && msg.tool_calls.length > 0) {
            for (const tc of msg.tool_calls) {
                blocks.value.push({
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
    }

    /**
     * 处理传统事件格式
     */
    function handleLegacyFormat(type: string, data: any) {
        const lastBlock = blocks.value[blocks.value.length - 1]

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
                    lastBlock.content += textContent
                } else {
                    blocks.value.push({ type: 'content', content: textContent })
                }
                break
            }

            case 'thinking_start':
                blocks.value.push({ type: 'thinking', content: '', subgraph: undefined })
                break

            case 'thinking':
            case 'thinking_delta': {
                const thinkingContent = data.content || data.delta || ''
                const currentSubgraph = data.subgraph

                if (lastBlock && lastBlock.type === 'thinking' && lastBlock.subgraph === currentSubgraph) {
                    lastBlock.content += thinkingContent
                } else {
                    blocks.value.push({
                        type: 'thinking',
                        content: thinkingContent,
                        subgraph: currentSubgraph
                    })
                }
                break
            }

            case 'tool_call':
                if (data.tool) {
                    blocks.value.push({
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
                blocks.value.push({
                    type: 'tool_output',
                    callId: data.id,
                    output: data.output,
                    subgraph: data.subgraph
                })
                break

            case 'chart':
                blocks.value.push({
                    type: 'chart',
                    data: data as ChartData
                })
                break

            case 'interrupt':
                isInterrupted.value = true
                interruptData.value = data
                blocks.value.push({
                    type: 'interrupt',
                    data: data
                })
                onInterrupt?.(data)
                break

            case 'done':
            case 'message_end':
                isStreaming.value = false
                onDone?.([...blocks.value])
                break

            case 'error':
                console.error('Stream error:', data.message || data.error)
                isStreaming.value = false
                onError?.(data.message || data.error || 'Unknown error')
                break
        }
    }

    /**
     * 处理 SSE 事件
     */
    function handleEvent(eventType: string, data: any) {
        // 开始流式传输
        if (!isStreaming.value) {
            isStreaming.value = true
        }

        // 判断格式：数组格式 vs 传统事件格式
        if (Array.isArray(data)) {
            if (data.length < 1) return
            handleArrayFormat(data[0], data[1] || {})
        } else {
            const type = data.type || eventType
            handleLegacyFormat(type, data)
        }
    }

    /**
     * 处理错误
     */
    function handleError(error: Error) {
        console.error('[StreamParser] Error:', error)
        isStreaming.value = false
        onError?.(error.message)
    }

    /**
     * 重置状态
     */
    function reset() {
        blocks.value = []
        isStreaming.value = false
        isInterrupted.value = false
        interruptData.value = null
    }

    return {
        blocks,
        isStreaming,
        isInterrupted,
        interruptData,
        handleEvent,
        handleError,
        reset
    }
}
