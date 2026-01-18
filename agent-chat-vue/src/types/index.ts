/**
 * API 类型定义
 */

export interface Message {
    id: string
    role: 'user' | 'assistant' | 'system' | 'tool'
    content: string
    thinking?: string
    toolCalls?: ToolCall[]
    chartData?: ChartData
    createdAt: Date
}

export interface ToolCall {
    name: string
    args: Record<string, unknown>
    result?: string
}

export interface ChartData {
    type: 'echarts'
    option: Record<string, unknown>
    title?: string
    description?: string
}

export interface Session {
    id: string
    title: string
    messages: Message[]
    isInterrupted: boolean
    interruptData?: InterruptData
    createdAt: Date
    updatedAt: Date
}

export interface InterruptData {
    reason: string
    preview?: Record<string, unknown>
}

// SSE 事件类型
export type SSEEventType =
    | 'message_start'
    | 'message_end'
    | 'content_delta'
    | 'thinking_start'
    | 'thinking_delta'
    | 'thinking_end'
    | 'tool_start'
    | 'tool_result'
    | 'chart'
    | 'interrupt'
    | 'error'

export interface SSEEvent {
    event: SSEEventType
    data: Record<string, unknown>
}
