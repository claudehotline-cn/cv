/**
 * Agent SDK - Vue Adapter
 * 
 * Vue 3 Composition API 封装
 */

import { ref, type Ref, readonly } from 'vue'
import { AgentClient, type AgentClientOptions } from '../core/client'
import type { MessageBlock, ChatState, ResumeOptions } from '../core/types'

export interface UseStreamOptions extends Omit<AgentClientOptions, 'onBlock' | 'onDone' | 'onInterrupt' | 'onError'> {
    /** 每个 block 解析完成时回调 */
    onBlock?: (block: MessageBlock) => void
    /** 流结束时回调 */
    onDone?: (blocks: MessageBlock[]) => void
    /** 发生中断时回调 */
    onInterrupt?: (data: any) => void
    /** 发生错误时回调 */
    onError?: (error: Error) => void
}

export interface UseStreamResult {
    /** 消息块列表 (只读) */
    blocks: Readonly<Ref<MessageBlock[]>>
    /** 是否正在流式传输 */
    isStreaming: Readonly<Ref<boolean>>
    /** 是否被中断 */
    isInterrupted: Readonly<Ref<boolean>>
    /** 中断数据 */
    interruptData: Readonly<Ref<any>>
    /** 发送消息 */
    submit: (sessionId: string, message: string) => Promise<void>
    /** 恢复中断 */
    resume: (sessionId: string, decision: 'approve' | 'reject', feedback?: string) => Promise<void>
    /** 重置状态 */
    reset: () => void
}

/**
 * Vue Composable for Agent Streaming
 * 
 * @example
 * ```vue
 * <script setup>
 * import { useStream } from '@/agent-sdk/vue'
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

    return {
        blocks: readonly(blocks),
        isStreaming: readonly(isStreaming),
        isInterrupted: readonly(isInterrupted),
        interruptData: readonly(interruptData),
        submit,
        resume,
        reset
    }
}
