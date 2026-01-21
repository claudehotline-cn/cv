/**
 * Agent SDK - Core Types
 * 
 * 框架无关的类型定义
 */

// =============================================================================
// Message Block Types
// =============================================================================

export type BlockType = 'thinking' | 'content' | 'tool_call' | 'tool_output' | 'chart' | 'interrupt'

export interface ToolCall {
    id: string
    name: string
    args: Record<string, any>
}

export interface ChartData {
    type?: string
    option?: Record<string, any>
    [key: string]: any
}

export interface MessageBlock {
    type: BlockType
    content?: string
    subgraph?: string
    call?: ToolCall
    callId?: string
    output?: string
    data?: any
}

// =============================================================================
// Client Configuration
// =============================================================================

export interface ClientConfig {
    /** API 基础 URL */
    baseUrl: string
    /** 默认 headers */
    headers?: Record<string, string>
    /** 调试模式 */
    debug?: boolean
}

// =============================================================================
// Stream Callbacks
// =============================================================================

export interface StreamCallbacks {
    /** 每个 block 解析完成时回调 */
    onBlock?: (block: MessageBlock) => void
    /** 流结束时回调 */
    onDone?: (blocks: MessageBlock[]) => void
    /** 发生中断时回调 */
    onInterrupt?: (data: any) => void
    /** 发生错误时回调 */
    onError?: (error: Error) => void
}

// =============================================================================
// Chat State
// =============================================================================

export interface ChatState {
    blocks: MessageBlock[]
    isStreaming: boolean
    isInterrupted: boolean
    interruptData: any | null
}

// =============================================================================
// API Types
// =============================================================================

export interface ResumeOptions {
    decision: 'approve' | 'reject'
    feedback?: string
}
