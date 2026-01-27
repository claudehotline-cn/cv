/**
 * API 类型定义
 */

export type MessageBlock =
    | ThinkingBlock
    | ToolCallBlock
    | ToolOutputBlock
    | ContentBlock
    | ChartBlock
    | InterruptBlock
    | AsyncTaskBlock

export interface AsyncTaskBlock {
    type: 'async_task'
    taskId: string
    content: string // task name or description
    progress: number
    status: string // 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
    resultUrl?: string
    error?: string
}

export interface ThinkingBlock {
    type: 'thinking'
    content: string
    subgraph?: string
}

export interface ToolCallBlock {
    type: 'tool_call'
    call: ToolCall
    subgraph?: string
}

export interface ToolOutputBlock {
    type: 'tool_output'
    callId: string
    output: string
    subgraph?: string
}

export interface ContentBlock {
    type: 'content'
    content: string
}

export interface ChartBlock {
    type: 'chart'
    data: ChartData
}

export interface InterruptBlock {
    type: 'interrupt'
    data: InterruptData
}

export interface Message {
    id: string
    role: 'user' | 'assistant' | 'system' | 'tool'
    blocks: MessageBlock[]
    createdAt: Date
}

export interface ToolCall {
    id?: string
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
