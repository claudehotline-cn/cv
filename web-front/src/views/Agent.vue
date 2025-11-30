<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentApi, isAgentEnabled, type AgentMessage, type AgentControlResult } from '@/api/agent'

const agentEnabled = isAgentEnabled()
const threadId = ref<string>(`manual-${Date.now()}`)
const messages = ref<AgentMessage[]>([])
const controlResult = ref<AgentControlResult | null>(null)
const input = ref<string>('')
const sending = ref(false)
const threadHistory = ref<string[]>(loadThreadHistory())

function loadThreadHistory(): string[] {
  try {
    const raw = window.localStorage.getItem('cv_agent_threads')
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (Array.isArray(arr)) {
      return arr.filter((x) => typeof x === 'string')
    }
  } catch {
    // ignore
  }
  return []
}

function recordThread(id: string) {
  if (!id) return
  const existing = threadHistory.value.filter((t) => t !== id)
  existing.unshift(id)
  threadHistory.value = existing.slice(0, 20)
  try {
    window.localStorage.setItem('cv_agent_threads', JSON.stringify(threadHistory.value))
  } catch {
    // ignore
  }
}

async function send() {
  if (!input.value.trim()) return
  if (!threadId.value.trim()) {
    ElMessage.warning('请先填写线程 ID')
    return
  }
  if (!agentEnabled) {
    ElMessage.info('Agent 已禁用，当前仅展示前端示例 UI。')
    return
  }
  const userMsg: AgentMessage = { role: 'user', content: input.value.trim() }
  messages.value.push(userMsg)
  recordThread(threadId.value.trim())
  const payload = {
    messages: [...messages.value],
  }
  sending.value = true
  try {
    const resp = await agentApi.invokeThread(threadId.value, payload)
    if (resp.message) {
      messages.value.push(resp.message)
    }
    controlResult.value = resp.control_result ?? null
    input.value = ''
  } catch (e: any) {
    ElMessage.error(e?.message || '调用 Agent 失败')
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <el-card shadow="never" class="agent-card">
    <template #header>
      <div class="head">
        <div class="left">
          <span class="title">Agent 控制台</span>
          <el-input
            v-model="threadId"
            size="small"
            class="thread-input"
            placeholder="线程 ID（例如 pipeline:cam_01）"
          />
        </div>
        <div class="right">
          <el-tag v-if="!agentEnabled" type="info">Agent 已禁用（仅前端模拟）</el-tag>
          <el-tag v-else type="success">Agent 已启用</el-tag>
        </div>
      </div>
      <div v-if="threadHistory.length" class="history">
        <span class="label">最近线程：</span>
        <el-tag
          v-for="tid in threadHistory"
          :key="tid"
          size="small"
          class="thread-tag"
          @click="threadId = tid"
        >
          {{ tid }}
        </el-tag>
      </div>
    </template>

    <div class="chat">
      <div class="messages">
        <div
          v-for="(m, idx) in messages"
          :key="idx"
          class="msg"
          :class="m.role"
        >
          <div class="role">
            {{
              m.role === 'user'
                ? '用户'
                : m.role === 'assistant'
                  ? 'Agent'
                  : m.role === 'system'
                    ? 'System'
                    : 'Tool'
            }}
          </div>
          <div class="content">{{ m.content }}</div>
        </div>
        <div v-if="controlResult" class="control-result">
          <div class="role">ControlResult</div>
          <div class="control-summary">
            <span class="field">op: {{ controlResult.op }}</span>
            <span class="field">mode: {{ controlResult.mode }}</span>
            <span class="field">success: {{ controlResult.success ? 'true' : 'false' }}</span>
          </div>
          <pre class="content">{{ JSON.stringify(controlResult, null, 2) }}</pre>
        </div>
      </div>
      <div class="input-bar">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          placeholder="输入要发送给 Agent 的指令，例如：'计划删除 pipeline cam_01。'"
        />
        <div class="actions">
          <el-button
            type="primary"
            size="small"
            :loading="sending"
            :disabled="!agentEnabled"
            @click="send"
          >
            发送
          </el-button>
        </div>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.agent-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title {
  font-weight: 600;
}
.thread-input {
  width: 260px;
}
.history {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.history .label {
  font-size: 12px;
  opacity: .7;
}
.thread-tag {
  cursor: pointer;
}
.chat {
  display: flex;
  flex-direction: column;
  height: calc(100% - 12px);
}
.messages {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--va-border);
  border-radius: 4px;
  background: var(--va-surface-2, #0f172a);
}
.msg {
  margin-bottom: 8px;
}
.msg .role {
  font-size: 12px;
  opacity: .7;
}
.msg .content {
  white-space: pre-wrap;
}
.msg.user .role { color: #3b82f6; }
.msg.assistant .role { color: #22c55e; }
.control-result {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px dashed var(--va-border);
}
.control-result .control-summary {
  font-size: 12px;
  margin-bottom: 4px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.control-result .content {
  font-size: 12px;
}
.input-bar {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
