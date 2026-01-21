/**
 * Chat Store - 管理聊天状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Session } from '@/types'
import apiClient from '@/api/client'
import { useStreamParser } from '@/composables/useStreamParser'

export const useChatStore = defineStore('chat', () => {
    // 状态
    const sessions = ref<Session[]>([])
    const currentSessionId = ref<string | null>(null)
    const messages = ref<Message[]>([])
    const isLoading = ref(false)
    const currentAgentId = ref<string | null>(null)

    // Stream parser instance
    const streamParser = useStreamParser({
        onDone: (blocks) => {
            // 流结束时，将 blocks 转换为消息
            const aiMessage: Message = {
                id: `ai-${Date.now()}`,
                role: 'assistant',
                blocks: [...blocks],
                createdAt: new Date(),
            }
            messages.value.push(aiMessage)
            streamParser.reset()
        },
        onError: (error) => {
            console.error('Stream error:', error)
        },
        debug: false
    })

    // 从 parser 导出响应式状态
    const streamingBlocks = streamParser.blocks
    const isStreaming = streamParser.isStreaming
    const isInterrupted = streamParser.isInterrupted
    const interruptData = streamParser.interruptData

    // 当前 abort 控制器
    let abortStream: (() => void) | null = null

    // 计算属性
    const currentSession = computed(() =>
        sessions.value.find(s => s.id === currentSessionId.value)
    )

    // 操作
    async function loadSessions() {
        isLoading.value = true
        try {
            const result = await apiClient.listSessions()
            sessions.value = result.sessions || []
        } finally {
            isLoading.value = false
        }
    }

    async function createSession(title?: string) {
        const agentId = currentAgentId.value
        const session = await apiClient.createSession(title, agentId || undefined)
        sessions.value.unshift(session)
        currentSessionId.value = session.id
        messages.value = []
        return session
    }

    function setCurrentAgent(agentId: string) {
        currentAgentId.value = agentId
    }

    async function selectSession(sessionId: string) {
        const session = await apiClient.getSession(sessionId)
        currentSessionId.value = sessionId
        messages.value = session.messages || []
        isInterrupted.value = session.is_interrupted || false
        interruptData.value = session.interrupt_data
    }

    function resetSession() {
        currentSessionId.value = null
        messages.value = []
        isInterrupted.value = false
        interruptData.value = null
        streamingBlocks.value = []
    }

    async function deleteSession(sessionId: string) {
        await apiClient.deleteSession(sessionId)
        sessions.value = sessions.value.filter(s => s.id !== sessionId)
        if (currentSessionId.value === sessionId) {
            currentSessionId.value = null
            messages.value = []
        }
    }

    function sendMessage(content: string) {
        if (!currentSessionId.value || isStreaming.value) return

        // 添加用户消息
        const userMessage: Message = {
            id: `temp-${Date.now()}`,
            role: 'user',
            blocks: [{ type: 'content', content }],
            createdAt: new Date(),
        }
        messages.value.push(userMessage)

        // 重置流状态
        streamParser.reset()

        // 开始流式请求
        abortStream = apiClient.streamChat(
            currentSessionId.value,
            content,
            streamParser.handleEvent,
            streamParser.handleError
        )
    }

    function sendFeedback(decision: 'approve' | 'reject', message?: string) {
        if (!currentSessionId.value) return

        streamParser.reset()

        abortStream = apiClient.streamFeedback(
            currentSessionId.value,
            { decision, message },
            streamParser.handleEvent,
            streamParser.handleError
        )
    }

    function stopStream() {
        if (abortStream) {
            abortStream()
            abortStream = null
            isStreaming.value = false
        }
    }

    return {
        sessions,
        currentSessionId,
        messages,
        isLoading,
        isStreaming,
        streamingBlocks,
        isInterrupted,
        interruptData,
        currentSession,
        currentAgentId,
        loadSessions,
        createSession,
        selectSession,
        deleteSession,
        sendMessage,
        sendFeedback,
        stopStream,
        setCurrentAgent,
        resetSession,
    }
})
