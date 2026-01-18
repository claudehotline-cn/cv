/**
 * Chat Store - 管理聊天状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Session, ChartData } from '@/types'
import apiClient from '@/api/client'

export const useChatStore = defineStore('chat', () => {
    // 状态
    const sessions = ref<Session[]>([])
    const currentSessionId = ref<string | null>(null)
    const messages = ref<Message[]>([])
    const isLoading = ref(false)
    const isStreaming = ref(false)
    const streamingContent = ref('')
    const streamingThinking = ref('')
    const isInterrupted = ref(false)
    const interruptData = ref<any>(null)
    const currentChart = ref<ChartData | null>(null)

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
        const session = await apiClient.createSession(title)
        sessions.value.unshift(session)
        currentSessionId.value = session.id
        messages.value = []
        return session
    }

    async function selectSession(sessionId: string) {
        const session = await apiClient.getSession(sessionId)
        currentSessionId.value = sessionId
        messages.value = session.messages || []
        isInterrupted.value = session.is_interrupted || false
        interruptData.value = session.interrupt_data
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
            content,
            createdAt: new Date(),
        }
        messages.value.push(userMessage)

        // 重置流状态
        isStreaming.value = true
        streamingContent.value = ''
        streamingThinking.value = ''
        currentChart.value = null

        // 开始流式请求
        abortStream = apiClient.streamChat(
            currentSessionId.value,
            content,
            handleSSEEvent,
            handleSSEError
        )
    }

    function handleSSEEvent(eventType: string, data: any) {
        switch (eventType) {
            case 'message_start':
                // 消息开始
                break

            case 'content_delta':
                streamingContent.value += data.delta || ''
                break

            case 'thinking_start':
                streamingThinking.value = ''
                break

            case 'thinking_delta':
                streamingThinking.value += data.delta || ''
                break

            case 'tool_start':
                // 可以在这里添加工具调用状态
                break

            case 'chart':
                currentChart.value = data as ChartData
                break

            case 'interrupt':
                isInterrupted.value = true
                interruptData.value = data
                break

            case 'message_end':
                // 消息结束，保存到消息列表
                const aiMessage: Message = {
                    id: data.id || `ai-${Date.now()}`,
                    role: 'assistant',
                    content: streamingContent.value,
                    thinking: streamingThinking.value || undefined,
                    chartData: currentChart.value || undefined,
                    createdAt: new Date(),
                }
                messages.value.push(aiMessage)

                // 重置流状态
                isStreaming.value = false
                streamingContent.value = ''
                streamingThinking.value = ''
                break

            case 'error':
                console.error('Stream error:', data.message)
                isStreaming.value = false
                break
        }
    }

    function handleSSEError(error: Error) {
        console.error('SSE error:', error)
        isStreaming.value = false
    }

    function sendFeedback(decision: 'approve' | 'reject', message?: string) {
        if (!currentSessionId.value) return

        isStreaming.value = true
        streamingContent.value = ''

        abortStream = apiClient.streamFeedback(
            currentSessionId.value,
            { decision, message },
            handleSSEEvent,
            handleSSEError
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
        // 状态
        sessions,
        currentSessionId,
        messages,
        isLoading,
        isStreaming,
        streamingContent,
        streamingThinking,
        isInterrupted,
        interruptData,
        currentChart,
        currentSession,
        // 操作
        loadSessions,
        createSession,
        selectSession,
        deleteSession,
        sendMessage,
        sendFeedback,
        stopStream,
    }
})
