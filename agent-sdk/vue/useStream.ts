/**
 * Agent SDK - Vue Adapter
 * 
 * Vue 3 Composition API 封装
 */

import { ref, type Ref } from 'vue'
import { AgentClient, type AgentClientOptions } from '../core/client'
import type { MessageBlock } from '../core/types'

export interface UseStreamOptions extends Omit<AgentClientOptions, 'onBlock' | 'onUpdate' | 'onDone' | 'onInterrupt' | 'onError'> {
    /** 每个 block 解析完成时回调 */
    onBlock?: (block: MessageBlock) => void
    /** block 内容更新时回调 */
    onUpdate?: (block: MessageBlock, index: number) => void
    /** 流结束时回调 */
    onDone?: (blocks: MessageBlock[]) => void
    /** 发生中断时回调 */
    onInterrupt?: (data: any) => void
    /** 发生错误时回调 */
    onError?: (error: Error) => void
}

export interface UseStreamResult {
    /** 消息块列表 */
    blocks: Ref<MessageBlock[]>
    /** 是否正在流式传输 */
    isStreaming: Ref<boolean>
    /** 是否被中断 */
    isInterrupted: Ref<boolean>
    /** 中断数据 */
    interruptData: Ref<any>
    /** 发送消息 */
    submit: (sessionId: string, message: string) => Promise<void>
    /** 恢复中断 */
    resume: (sessionId: string, decision: 'approve' | 'reject', feedback?: string) => Promise<void>
    /** 重置状态 */
    reset: () => void
    /** 停止当前流 */
    stop: () => void
    /** 设置中断状态（用于从服务端恢复状态） */
    setInterruptState: (interrupted: boolean, data?: any) => void
    /** 处理单个事件（用于外部流控制） */
    handleEvent: (event: any) => void
    /** 处理错误 */
    handleError: (error: Error) => void
}

/**
 * Vue Composable for Agent Streaming
 * 
 * @example
 * ```vue
 * <script setup>
 * import { useStream } from '@agent-sdk/vue'
 * 
 * const { blocks, isStreaming, submit, resume } = useStream({
 *   baseUrl: '/api'
 * })
 * 
 * async function sendMessage() {
 *   await submit('session-123', 'Hello!')
 * }
 * </script>
 * ```
 */
export function useStream(options: UseStreamOptions): UseStreamResult {
    // 响应式状态
    const blocks = ref<MessageBlock[]>([])
    const isStreaming = ref(false)
    const isInterrupted = ref(false)
    const interruptData = ref<any>(null)

    // 创建客户端
    const client = new AgentClient({
        ...options,
        onBlock: (block) => {
            blocks.value.push(block)
            options.onBlock?.(block)
        },
        onUpdate: (_block, _index) => {
            // 触发 Vue 响应式更新：重新赋值数组引用
            // 不能用 splice+spread 因为 StreamParser 持有原对象引用
            blocks.value = [...blocks.value]
            options.onUpdate?.(_block, _index)
        },
        onDone: (allBlocks) => {
            isStreaming.value = false
            options.onDone?.(allBlocks)
        },
        onInterrupt: (data) => {
            isInterrupted.value = true
            interruptData.value = data
            options.onInterrupt?.(data)
        },
        onError: (error) => {
            isStreaming.value = false
            options.onError?.(error)
        }
    })

    /**
     * 发送消息
     */
    async function submit(sessionId: string, message: string): Promise<void> {
        reset()
        isStreaming.value = true

        try {
            await client.chat(sessionId, message)
        } catch (error) {
            isStreaming.value = false
            throw error
        }
    }

    /**
     * 恢复中断的会话
     */
    async function resume(
        sessionId: string,
        decision: 'approve' | 'reject',
        feedback?: string
    ): Promise<void> {
        isInterrupted.value = false
        interruptData.value = null
        isStreaming.value = true

        try {
            await client.resume(sessionId, { decision, feedback })
        } catch (error) {
            isStreaming.value = false
            throw error
        }
    }

    /**
     * 重置状态
     */
    function reset(): void {
        blocks.value = []
        isStreaming.value = false
        isInterrupted.value = false
        interruptData.value = null
        client.reset()
    }

    /**
     * 停止当前流
     */
    function stop(): void {
        client.abort()
        isStreaming.value = false
    }

    /**
     * 设置中断状态（用于从服务端恢复状态）
     */
    function setInterruptState(interrupted: boolean, data?: any): void {
        isInterrupted.value = interrupted
        interruptData.value = data ?? null
    }

    /**
     * 处理单个事件（用于外部流控制）
     */
    function handleEvent(event: any): void {
        client.processEvent(event)
    }

    /**
     * 处理错误
     */
    function handleError(error: Error): void {
        isStreaming.value = false
        options.onError?.(error)
    }

    return {
        blocks,
        isStreaming,
        isInterrupted,
        interruptData,
        submit,
        resume,
        reset,
        stop,
        setInterruptState,
        handleEvent,
        handleError
    }
}
