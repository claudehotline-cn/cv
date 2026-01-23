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

    // 异步任务相关
    const asyncMode = ref(false)
    const currentTask = ref<{
        id: string
        name: string
        progress: number
        status: string
        message?: string
    } | null>(null)

    // 任务 SSE 连接持有
    let taskEventSource: (() => void) | null = null

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

            // 设置当前任务并订阅状态
            currentTask.value = {
                id: taskId,
                name: content.slice(0, 20),
                progress: 0,
                status: 'pending',
                message: 'Task queued...'
            }

            subscribeTaskStream(taskId)

        } catch (error) {
            console.error('Failed to execute async task:', error)
        }
    }

    function subscribeTaskStream(taskId: string) {
        // 关闭旧连接
        if (taskEventSource) {
            taskEventSource()
            taskEventSource = null
        }

        taskEventSource = apiClient.streamTask(
            taskId,
            (data: any) => {
                // data: { type: 'chunk'|'progress', data: ... }
                // 注意：routes/tasks.py 返回的是 { type: ..., data: ... }
                // 但是 worker.py 发布的是 { type: 'chunk', data: str }

                // 这里我们主要关注更新 Store 状态和 消息块

                if (data.type === 'chunk') {
                    // Update task card in chat messages?
                    // Ideally we should stream output content if there is text?
                    // Currently `chunk` is raw output.

                    // For now, let's just update generic progress if not provided
                    if (currentTask.value) {
                        currentTask.value.message = "Processing..."
                    }
                }

                // 我们还需要轮询 status 或者依赖 worker 发送 progress 事件?
                // worker.py 并没有发送 'progress' 事件到 stream!
                // worker.py 只有: await redis.xadd(..., {type: 'chunk', ...})

                // Wait, worker.py ALSO updates DB status & progress.
                // But tasks.py stream ONLY reads from Redis stream.
                // So frontend won't receive progress updates unless we also push them to Redis.

                // Check worker.py again:
                // It calls task_service.update_progress (DB update)
                // It calls event_bus.publish('chunk')

                // It SHOULD also publish progress to event bus if we want real-time progress bar.
                // I missed that in worker.py refactor.
            },
            (err) => console.error('Task stream error', err)
        )

        // Polling fallback to keep progress sync?
        // Let's implement simple polling for status/progress since worker doesn't emit progress to stream yet
        const pollInterval = setInterval(async () => {
            try {
                const task = await apiClient.getTask(taskId)
                if (currentTask.value && currentTask.value.id === taskId) {
                    currentTask.value.progress = task.progress
                    currentTask.value.status = task.status
                    currentTask.value.message = task.progress_message

                    // Update the message block in chat history as well
                    const msg = messages.value.find((m: Message) => m.blocks.some((b: any) => b.type === 'async_task' && b.taskId === taskId))
                    if (msg) {
                        const block = msg.blocks.find((b: any) => b.type === 'async_task') as any
                        if (block) {
                            block.progress = task.progress
                            block.status = task.status
                            block.content = task.progress_message || block.content
                        }
                    }

                    if (['completed', 'failed', 'cancelled'].includes(task.status)) {
                        clearInterval(pollInterval)
                        if (taskEventSource) taskEventSource()
                        // If completed, maybe show result? 
                        // For now keep it simple.
                    }
                } else {
                    clearInterval(pollInterval)
                }
            } catch (e) { /* ignore */ }
        }, 1000)
    }

    async function cancelTask(taskId: string) {
        await apiClient.cancelTask(taskId)
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
        currentTask,

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
        cancelTask
    }
})
