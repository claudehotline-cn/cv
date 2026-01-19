/**
 * Chat Store - 管理聊天状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Session, ChartData, ToolCall } from '@/types'
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
    const streamingToolCalls = ref<ToolCall[]>([])
    const isInterrupted = ref(false)
    const interruptData = ref<any>(null)
    const currentChart = ref<ChartData | null>(null)
    const currentAgentId = ref<string | null>(null)

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
        interruptData.value = session.interrupt_data
    }

    function resetSession() {
        currentSessionId.value = null
        messages.value = []
        isInterrupted.value = false
        interruptData.value = null
        currentChart.value = null
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
        streamingToolCalls.value = []
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
        // Handle new API event types (type field) or legacy (event field)
        const type = data.type || eventType

        switch (type) {
            case 'message_start':
                // 消息开始
                break

            case 'content':
            case 'content_delta':
                // Handle nested content array format from vLLM: [{type: 'text', text: '...'}]
                if (Array.isArray(data.content)) {
                    const textContent = data.content
                        .filter((c: any) => c.type === 'text')
                        .map((c: any) => c.text)
                        .join('')
                    streamingContent.value += textContent
                } else {
                    streamingContent.value += data.content || data.delta || ''
                }
                break

            case 'thinking_start':
                streamingThinking.value = ''
                break

            case 'thinking':
            case 'thinking_delta':
                // Handle both legacy 'thinking_delta' and new 'thinking' event
                streamingThinking.value += data.content || data.delta || ''
                break

            case 'tool_start':
                // Legacy
                break

            case 'tool_call':
                if (data.tool) {
                    streamingToolCalls.value.push({
                        id: data.id,
                        name: data.tool,
                        args: data.args || {},
                        result: undefined
                    })
                }
                break

            case 'tool_output':
                if (data.id) {
                    const call = streamingToolCalls.value.find(c => c.id === data.id)
                    if (call) {
                        call.result = data.output
                    }
                }
                break

            case 'chart':
                currentChart.value = data as ChartData
                break

            case 'interrupt':
                isInterrupted.value = true
                interruptData.value = data
                break

            case 'done':
            case 'message_end':
                // 消息结束，保存到消息列表
                const aiMessage: Message = {
                    id: data.id || `ai-${Date.now()}`,
                    role: 'assistant',
                    content: streamingContent.value,
                    thinking: streamingThinking.value || undefined,
                    toolCalls: streamingToolCalls.value.length > 0 ? [...streamingToolCalls.value] : undefined,
                    chartData: currentChart.value || undefined,
                    createdAt: new Date(),
                }
                messages.value.push(aiMessage)

                // 重置流状态
                isStreaming.value = false
                streamingContent.value = ''
                streamingThinking.value = ''
                streamingToolCalls.value = []
                break

            case 'error':
                console.error('Stream error:', data.message || data.error)
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
        streamingToolCalls,
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
        setCurrentAgent,
        resetSession,
        currentAgentId,
    }
})
