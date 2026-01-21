/**
 * Chat Store - 管理聊天状态
 * 
 * 使用 agent-sdk 的 useStream 进行流式聊天
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Message, Session } from '@/types'
import apiClient from '@/api/client'
import { useStream } from '@agent-sdk/vue'

export const useChatStore = defineStore('chat', () => {
    // 状态
    const sessions = ref<Session[]>([])
    const currentSessionId = ref<string | null>(null)
    const messages = ref<Message[]>([])
    const isLoading = ref(false)
    const currentAgentId = ref<string | null>(null)

    // 使用 SDK 的 useStream
    const stream = useStream({
        baseUrl: import.meta.env.VITE_API_URL || '/api',
        onDone: (blocks) => {
            // 流结束时，将 blocks 转换为消息
            const aiMessage: Message = {
                id: `ai-${Date.now()}`,
                role: 'assistant',
                blocks: [...blocks],
                createdAt: new Date(),
            }
            messages.value.push(aiMessage)
            stream.reset()
        },
        onError: (error) => {
            console.error('Stream error:', error)
        },
        debug: false
    })

    // 从 stream 导出响应式状态
    const streamingBlocks = stream.blocks
    const isStreaming = stream.isStreaming
    const isInterrupted = stream.isInterrupted
    const interruptData = stream.interruptData

    // 计算属性
    const currentSession = computed(() =>
        sessions.value.find(s => s.id === currentSessionId.value)
    )

    // Session 管理（使用 apiClient）
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
        stream.setInterruptState(
            session.is_interrupted || false,
            session.interrupt_data
        )
    }

    function resetSession() {
        currentSessionId.value = null
        messages.value = []
        stream.reset()
    }

    async function deleteSession(sessionId: string) {
        await apiClient.deleteSession(sessionId)
        sessions.value = sessions.value.filter(s => s.id !== sessionId)
        if (currentSessionId.value === sessionId) {
            currentSessionId.value = null
            messages.value = []
        }
    }

    // 聊天功能（完全使用 SDK）
    async function sendMessage(content: string) {
        if (!currentSessionId.value || isStreaming.value) return

        // 添加用户消息
        const userMessage: Message = {
            id: `temp-${Date.now()}`,
            role: 'user',
            blocks: [{ type: 'content', content }],
            createdAt: new Date(),
        }
        messages.value.push(userMessage)

        // 使用 SDK 发送消息
        try {
            await stream.submit(currentSessionId.value, content)
        } catch (error) {
            console.error('Failed to send message:', error)
        }
    }

    async function resumeChat(decision: 'approve' | 'reject', feedback: string) {
        if (!currentSessionId.value) return

        // 使用 SDK 恢复会话
        try {
            await stream.resume(currentSessionId.value, decision, feedback)
        } catch (error) {
            console.error('Failed to resume chat:', error)
        }
    }

    function stopStream() {
        stream.stop()
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
        resumeChat,
        stopStream,
        setCurrentAgent,
        resetSession,
    }
})
