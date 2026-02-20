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

function authHeaders() {
    const token = window.localStorage.getItem('auth.accessToken') || ''
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
}

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
        headers: authHeaders,
        onDone: (blocks) => {
            // 流结束时，将 blocks 转换为消息
            const aiMessage: Message = {
                id: `ai-${Date.now()}`,
                role: 'assistant',
                blocks: [...blocks] as any,
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
        tasks.value = []
        subscribeSessionTaskStream(session.id)
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
        await loadSessionTasks(sessionId)
        subscribeSessionTaskStream(sessionId)
    }

    function resetSession() {
        currentSessionId.value = null
        messages.value = []
        stream.reset()
        tasks.value = []
        stopSessionTaskStream()
    }

    async function deleteSession(sessionId: string) {
        await apiClient.deleteSession(sessionId)
        sessions.value = sessions.value.filter(s => s.id !== sessionId)
        if (currentSessionId.value === sessionId) {
            currentSessionId.value = null
            messages.value = []
            tasks.value = []
            stopSessionTaskStream()
        }
    }

    // 异步任务相关
    const asyncMode = ref(false)
    type AsyncTask = {
        id: string
        name: string
        progress: number
        status: string
        message?: string
        resultUrl?: string
        error?: string
        interruptData?: any
    }

    const tasks = ref<AsyncTask[]>([])
    const activeTasks = computed(() =>
        tasks.value.filter(t => ['pending', 'running', 'waiting_approval'].includes(t.status))
    )

    // 会话任务 SSE 连接持有（单会话单连接）
    let sessionTaskEventSource: (() => void) | null = null

    function stopSessionTaskStream() {
        if (sessionTaskEventSource) {
            sessionTaskEventSource()
            sessionTaskEventSource = null
        }
    }

    async function loadSessionTasks(sessionId: string) {
        try {
            const res = await apiClient.listSessionTasks(sessionId, { limit: 50 })
            const list = (res.tasks || []) as any[]
            tasks.value = list.map((t) => {
                const result = t.result || {}
                return {
                    id: t.id,
                    name: result.input_message?.slice(0, 20) || `Task ${String(t.id).slice(0, 8)}`,
                    progress: Number(t.progress || 0),
                    status: t.status,
                    message: t.progress_message,
                    resultUrl: result.audit_url,
                    error: t.error,
                    interruptData: result.interrupt_data,
                } as AsyncTask
            })
        } catch (e) {
            console.error('Failed to load session tasks', e)
            tasks.value = []
        }
    }

    function upsertTask(taskId: string, patch: Partial<AsyncTask> & { name?: string }) {
        const idx = tasks.value.findIndex(t => t.id === taskId)
        if (idx >= 0) {
            tasks.value[idx] = { ...tasks.value[idx], ...patch }
        } else {
            tasks.value.unshift({
                id: taskId,
                name: patch.name || `Task ${taskId.slice(0, 8)}`,
                progress: patch.progress ?? 0,
                status: patch.status || 'pending',
                message: patch.message,
                resultUrl: patch.resultUrl,
                error: patch.error,
            })
        }
    }

    function updateMessageTaskBlock(taskId: string, patch: Partial<any>) {
        const msg = messages.value.find((m: Message) =>
            m.blocks.some((b: any) => b.type === 'async_task' && b.taskId === taskId)
        )
        if (!msg) return
        const block = msg.blocks.find((b: any) => b.type === 'async_task' && b.taskId === taskId) as any
        if (!block) return
        Object.assign(block, patch)
    }

    function subscribeSessionTaskStream(sessionId: string) {
        stopSessionTaskStream()

        sessionTaskEventSource = apiClient.streamSessionTasks(
            sessionId,
            (data: any) => {
                const taskId = data.task_id || data.taskId
                if (!taskId) return

                const status = data.status
                const progress = data.progress !== undefined ? Number(data.progress) : undefined
                const message = data.message || data.progress_message || data.progressMessage

                let resultUrl: string | undefined
                if (data.result) {
                    const raw = data.result
                    try {
                        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
                        resultUrl = parsed?.audit_url || parsed?.result_url
                    } catch {
                        // ignore
                    }
                }
                if (!resultUrl && data.audit_url) resultUrl = data.audit_url

                if (data.type === 'task_progress' || data.type === 'task_cancel_requested') {
                    upsertTask(taskId, {
                        name: (data.title || '').slice(0, 20) || undefined,
                        status: status || 'running',
                        progress: progress,
                        message: message,
                    })
                    updateMessageTaskBlock(taskId, {
                        progress: progress,
                        status: status || 'running',
                        content: message || '执行中...',
                    })
                    return
                }

                if (data.type === 'task_waiting_approval') {
                    const interruptData = data.interrupt_data || data.interruptData
                    upsertTask(taskId, {
                        name: (data.title || '').slice(0, 20) || undefined,
                        status: 'waiting_approval',
                        progress: progress ?? 90,
                        message: message || '等待人工确认',
                        resultUrl,
                        interruptData,
                    })
                    updateMessageTaskBlock(taskId, {
                        progress: progress ?? 90,
                        status: 'waiting_approval',
                        content: message || '等待人工确认',
                        resultUrl,
                        interruptData,
                    })
                    return
                }

                if (data.type === 'task_completed') {
                    upsertTask(taskId, {
                        name: (data.title || '').slice(0, 20) || undefined,
                        status: 'completed',
                        progress: 100,
                        message: message || '完成',
                        resultUrl,
                    })
                    updateMessageTaskBlock(taskId, {
                        progress: 100,
                        status: 'completed',
                        content: message || '完成',
                        resultUrl,
                    })
                    return
                }

                if (data.type === 'task_failed') {
                    upsertTask(taskId, {
                        name: (data.title || '').slice(0, 20) || undefined,
                        status: 'failed',
                        progress: 100,
                        message: message || '失败',
                        error: data.error,
                    })
                    updateMessageTaskBlock(taskId, {
                        progress: 100,
                        status: 'failed',
                        content: data.error || message || '失败',
                        error: data.error,
                    })
                    return
                }

                if (data.type === 'task_cancelled') {
                    upsertTask(taskId, {
                        name: (data.title || '').slice(0, 20) || undefined,
                        status: 'cancelled',
                        progress: 100,
                        message: message || '已取消',
                    })
                    updateMessageTaskBlock(taskId, {
                        progress: 100,
                        status: 'cancelled',
                        content: message || '已取消',
                    })
                }
            },
            (err) => console.error('Session task stream error', err)
        )
    }

    // 聊天功能（完全使用 SDK）
    async function sendMessage(content: string) {
        if (!currentSessionId.value) return

        // 如果开启了异步模式
        if (asyncMode.value) {
            await executeAsync(content)
            return
        }

        if (isStreaming.value) return

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

    async function executeAsync(content: string) {
        if (!currentSessionId.value) return

        // 添加用户消息
        const userMessage: Message = {
            id: `temp-${Date.now()}`,
            role: 'user',
            blocks: [{ type: 'content', content }],
            createdAt: new Date(),
        }
        messages.value.push(userMessage)

        try {
            // 调用 executeTask API
            const res = await apiClient.executeTask(currentSessionId.value, content, {})
            const taskId = res.task_id

            // 添加助手消息（内嵌任务卡片）
            const aiMessage: Message = {
                id: `task-${taskId}`,
                role: 'assistant',
                blocks: [{
                    type: 'async_task',
                    taskId: taskId,
                    content: 'Task initialized',
                    progress: 0,
                    status: 'pending'
                }],
                createdAt: new Date(),
            }
            messages.value.push(aiMessage)

            // 加入任务列表（后续由 SSE 推进度/结果）
            upsertTask(taskId, {
                id: taskId,
                name: content.slice(0, 20),
                progress: 0,
                status: 'pending',
                message: 'Task queued...'
            })

        } catch (error) {
            console.error('Failed to execute async task:', error)
        }
    }

    async function cancelTask(taskId: string) {
        await apiClient.cancelTask(taskId)
    }

    async function resumeTask(taskId: string, decision: 'approve' | 'reject', feedback: string = '') {
        try {
            await apiClient.resumeTask(taskId, decision, feedback)
            upsertTask(taskId, {
                status: 'running',
                message: '已提交审批，继续执行中...',
                progress: 90,
            })
            updateMessageTaskBlock(taskId, {
                status: 'running',
                content: '已提交审批，继续执行中...',
                progress: 90,
            })
        } catch (error) {
            console.error('Failed to resume task:', error)
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

        asyncMode,
        tasks,
        activeTasks,

        loadSessions,
        createSession,
        selectSession,
        deleteSession,
        sendMessage,
        resumeChat,
        stopStream,
        setCurrentAgent,
        resetSession,

        executeAsync,
        cancelTask,
        resumeTask,
    }
})
