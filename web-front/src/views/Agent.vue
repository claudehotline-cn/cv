<script setup lang="ts">
import { computed, onMounted, ref, nextTick, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { ElMessage } from 'element-plus'
import {
  agentApi,
  isAgentEnabled,
  type AgentMessage,
  type AgentControlResult,
  type AgentThreadSummary,
  type AgentChartResult,
  type DbChartResponse,
  type ExcelChartResponse,
} from '@/api/agent'
import AgentChartCard from '@/components/analytics/AgentChartCard.vue'

const agentEnabled = isAgentEnabled()
const threadId = ref<string>(`manual-${Date.now()}`)
const messages = ref<AgentMessage[]>([])
const controlResult = ref<AgentControlResult | null>(null)
const input = ref<string>('')
const sending = ref(false)
const threadHistory = ref<string[]>(loadThreadHistory())
const lastRawState = ref<any | null>(null)
const threadSummaries = ref<AgentThreadSummary[]>([])
const activeTab = ref<'chat' | 'threads' | 'charts'>('chat')
const currentMode = ref<'default' | 'control' | 'rag'>('default')
const showHistoryPanel = ref(false)
const searchQuery = ref<string>('')
const lastAgentData = ref<any | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)

// 图表分析相关状态
const dbForm = ref<{ dbName: string; query: string }>({ dbName: 'cv_cp', query: '' })
const dbLoading = ref(false)
const dbCharts = ref<AgentChartResult[]>([])
const dbInsight = ref<string | null>(null)
const dbError = ref<string | null>(null)
const dbResponse = ref<DbChartResponse | null>(null)

const excelForm = ref<{ fileId: string; sheetName: string; query: string }>({
  fileId: '',
  sheetName: '',
  query: '',
})
const excelLoading = ref(false)
const excelCharts = ref<AgentChartResult[]>([])
const excelInsight = ref<string | null>(null)
const excelError = ref<string | null>(null)
const excelResponse = ref<ExcelChartResponse | null>(null)

const chatModes = [
  {
    key: 'default' as const,
    label: '对话',
    description: '与控制平面 Agent 进行自然语言对话，查询 pipeline 状态与配置。',
  },
  {
    key: 'control' as const,
    label: '控制',
    description: '围绕 delete/hotswap/drain 等高危操作进行 plan/execute 协同控制。',
  },
  {
    key: 'rag' as const,
    label: '知识检索',
    description: '结合项目文档知识库，回答配置说明、错误排障等问题。',
  },
]

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
})

function renderMarkdown(content: string | undefined | null): string {
  if (!content) return ''
  return md.render(content)
}

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

const toolSteps = computed(() => {
  const data = lastAgentData.value
  if (data && Array.isArray(data.steps)) {
    return data.steps.filter((s: any) => s?.type === 'tool').map((s: any) => ({
      type: 'tool',
      content: String(s.content ?? ''),
    }))
  }
  const state = lastRawState.value
  if (!state || !Array.isArray(state.messages)) return []
  const out: { type: string; content: string }[] = []
  for (const m of state.messages) {
    const role = (m && (m.type || m.role)) as string | undefined
    if (role === 'tool') {
      out.push({ type: 'tool', content: String(m.content ?? '') })
    }
  }
  return out
})

const agentSteps = computed(() => {
  const data = lastAgentData.value
  if (!data || !Array.isArray(data.steps)) return []
  return data.steps as any[]
})

async function refreshThreadSummaries() {
  try {
    threadSummaries.value = await agentApi.listThreads()
  } catch {
    // ignore in UI；仅作为增强信息
  }
}

onMounted(() => {
  void refreshThreadSummaries()
  void scrollMessagesToBottom()
})

async function scrollMessagesToBottom() {
  await nextTick()
  const el = messagesContainer.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => messages.value.length,
  () => {
    void scrollMessagesToBottom()
  },
)

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
    lastRawState.value = resp.raw_state ?? null
    lastAgentData.value = resp.agent_data ?? null
    input.value = ''
    void refreshThreadSummaries()
    void scrollMessagesToBottom()
  } catch (e: any) {
    ElMessage.error(e?.message || '调用 Agent 失败')
  } finally {
    sending.value = false
  }
}

async function runDbChart() {
  if (!dbForm.value.query.trim()) return
  if (!agentEnabled) {
    ElMessage.info('Agent 已禁用，当前仅展示前端示例 UI。')
    return
  }
  dbLoading.value = true
  dbError.value = null
  try {
    const resp = await agentApi.dbChart({
      session_id: threadId.value || `db-${Date.now()}`,
      db_name: dbForm.value.dbName || undefined,
      query: dbForm.value.query,
    })
    dbResponse.value = resp
    dbCharts.value = resp.charts || []
    dbInsight.value = resp.insight || null
  } catch (e: any) {
    dbError.value = e?.message || '数据库分析失败'
  } finally {
    dbLoading.value = false
  }
}

async function runExcelChart() {
  if (!excelForm.value.fileId.trim() || !excelForm.value.query.trim()) return
  if (!agentEnabled) {
    ElMessage.info('Agent 已禁用，当前仅展示前端示例 UI。')
    return
  }
  excelLoading.value = true
  excelError.value = null
  try {
    const resp = await agentApi.excelChart({
      session_id: threadId.value || `excel-${Date.now()}`,
      file_id: excelForm.value.fileId,
      sheet_name: excelForm.value.sheetName || undefined,
      query: excelForm.value.query,
    })
    excelResponse.value = resp
    excelCharts.value = resp.charts || []
    excelInsight.value = resp.insight || null
  } catch (e: any) {
    excelError.value = e?.message || 'Excel 分析失败'
  } finally {
    excelLoading.value = false
  }
}

function switchMode(mode: 'default' | 'control' | 'rag') {
  currentMode.value = mode
}

function toggleHistoryPanel() {
  showHistoryPanel.value = !showHistoryPanel.value
}

const filteredThreadSummaries = computed(() => {
  const q = searchQuery.value.trim()
  if (!q) return threadSummaries.value
  return threadSummaries.value.filter((t) => {
    const hay = [
      t.thread_id || '',
      t.last_user_message || '',
      t.last_assistant_message || '',
    ].join(' ')
    return hay.includes(q)
  })
})
</script>

<template>
  <div class="agent-page">
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
    </template>

    <div class="mode-bar">
      <div class="mode-tabs">
        <div
          v-for="mode in chatModes"
          :key="mode.key"
          :class="['mode-tab', { active: currentMode === mode.key }]"
          @click="switchMode(mode.key)"
        >
          <span class="dot" />
          <span class="label">{{ mode.label }}</span>
        </div>
        <div
          class="mode-tab history-tab"
          :class="{ active: showHistoryPanel }"
          @click="toggleHistoryPanel"
        >
          <span class="dot history-dot" />
          <span class="label">历史对话</span>
        </div>
      </div>
      <div class="mode-desc">
        {{ chatModes.find(m => m.key === currentMode)?.description }}
      </div>
    </div>

    <div
      v-if="showHistoryPanel"
      class="history-panel-overlay"
      @click.self="toggleHistoryPanel"
    >
      <div class="history-panel-card">
        <div class="history-panel-header">
          <span>历史对话</span>
          <el-button size="small" text @click="toggleHistoryPanel">关闭</el-button>
        </div>
        <div class="history-panel-search">
          <el-input
            v-model="searchQuery"
            size="small"
            clearable
            placeholder="按 thread_id 或内容搜索"
          />
        </div>
        <div class="history-panel-list">
          <div
            v-if="!filteredThreadSummaries.length"
            class="history-panel-empty"
          >
            暂无历史记录，可先在右侧与 Agent 进行一次对话。
          </div>
          <el-table
            v-else
            :data="filteredThreadSummaries"
            size="small"
            border
          >
            <el-table-column prop="thread_id" label="Thread ID" min-width="220">
              <template #default="scope">
                <el-link
                  type="primary"
                  @click="
                    threadId = scope.row.thread_id;
                    activeTab = 'chat';
                    toggleHistoryPanel()
                  "
                >
                  {{ scope.row.thread_id }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="last_control_op" label="最近操作" min-width="140" />
            <el-table-column prop="last_control_mode" label="模式" min-width="80" />
            <el-table-column
              prop="last_control_success"
              label="结果"
              min-width="80"
            >
              <template #default="scope">
                <el-tag
                  v-if="scope.row.last_control_success === true"
                  type="success"
                  size="small"
                >
                  成功
                </el-tag>
                <el-tag
                  v-else-if="scope.row.last_control_success === false"
                  type="danger"
                  size="small"
                >
                  失败
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column
              prop="updated_at"
              label="更新时间"
              min-width="160"
            />
          </el-table>
        </div>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="agent-tabs">
      <el-tab-pane label="对话" name="chat">
        <div class="agent-main">
          <div class="chat-panel">
            <div
              ref="messagesContainer"
              class="messages-container"
            >
              <div v-if="!messages.length" class="welcome">
                <h3>开始与控制平面 Agent 对话</h3>
                <p>可以用自然语言执行管线查询、plan/execute 控制等操作。</p>
                <div class="quick-actions">
                  <span>快速示例：</span>
                  <el-button
                    size="small"
                    @click="input = '列出当前所有 pipeline，并说明状态。'; send()"
                  >
                    列出 pipelines
                  </el-button>
                  <el-button
                    size="small"
                    @click="input = '检查 pipeline demo_pipeline 的状态。'; send()"
                  >
                    检查某个 pipeline
                  </el-button>
                </div>
              </div>

              <div
                v-for="(m, idx) in messages"
                :key="idx"
                class="message-row"
                :class="m.role"
              >
                <div class="avatar">
                  <div v-if="m.role === 'user'" class="avatar-circle user">U</div>
                  <div v-else-if="m.role === 'assistant'" class="avatar-circle agent">A</div>
                  <div v-else class="avatar-circle sys">S</div>
                </div>
                <div class="bubble">
                  <div class="meta">
                    <span class="role-text">
                      {{
                        m.role === 'user'
                          ? '用户'
                          : m.role === 'assistant'
                            ? 'Agent'
                            : m.role === 'system'
                              ? 'System'
                            : 'Tool'
                      }}
                    </span>
                  </div>
                  <div class="content" v-html="renderMarkdown(m.content)" />
                </div>
              </div>
            </div>

            <div class="input-area">
              <el-input
                v-model="input"
                type="textarea"
                :rows="3"
                placeholder="输入要发送给 Agent 的指令，例如：'计划删除 pipeline cam_01。'"
                @keydown.ctrl.enter.prevent="send"
              />
              <div class="input-actions">
                <span class="hint">Ctrl + Enter 发送</span>
                <el-button
                  type="primary"
                  size="small"
                  :loading="sending"
                  :disabled="!agentEnabled || !input.trim()"
                  @click="send"
                >
                  发送
                </el-button>
              </div>
            </div>
          </div>

          <div class="side-panel">
            <el-card
              v-if="agentSteps.length"
              shadow="never"
              class="side-card"
              header="Agent 思考流程"
            >
              <ul class="agent-step-list">
                <li
                  v-for="(step, idx) in agentSteps"
                  :key="step.id || idx"
                  class="agent-step"
                  :class="`step-${step.type}`"
                >
                  <div class="line" />
                  <div class="dot" />
                  <div class="body">
                    <div class="row">
                      <span class="badge">{{ step.type }}</span>
                      <span v-if="step.tool_name" class="tool-name">
                        {{ step.tool_name }}
                      </span>
                      <span v-if="step.status" class="status">
                        {{ step.status }}
                      </span>
                    </div>
                    <div
                      class="content"
                      v-html="renderMarkdown(step.content || '...')"
                    />
                  </div>
                </li>
              </ul>
            </el-card>

            <el-card shadow="never" class="side-card" header="最近控制结果">
              <div v-if="!controlResult" class="side-empty">
                暂无控制操作，可通过 control 协议发起 delete/hotswap/drain。
              </div>
              <div v-else class="control-summary-block">
                <div class="row">
                  <span class="label">op</span>
                  <span class="value">{{ controlResult.op }}</span>
                </div>
                <div class="row">
                  <span class="label">mode</span>
                  <el-tag
                    size="small"
                    :type="controlResult.mode === 'plan' ? 'info' : 'warning'"
                  >
                    {{ controlResult.mode }}
                  </el-tag>
                </div>
                <div class="row">
                  <span class="label">success</span>
                  <el-tag
                    v-if="controlResult.success"
                    size="small"
                    type="success"
                  >
                    成功
                  </el-tag>
                  <el-tag
                    v-else
                    size="small"
                    type="danger"
                  >
                    失败
                  </el-tag>
                </div>
                <div class="detail">
                  <div class="detail-label">原始结果</div>
                  <pre class="detail-json">{{ JSON.stringify(controlResult, null, 2) }}</pre>
                </div>
              </div>
            </el-card>
            <el-card
              v-if="toolSteps.length"
              shadow="never"
              class="side-card"
              header="Tool 调用步骤"
            >
              <ul class="tool-step-list">
                <li v-for="(step, idx) in toolSteps" :key="idx">
                  <span class="idx">#{{ idx + 1 }}</span>
                  <span class="text">{{ step.content }}</span>
                </li>
              </ul>
            </el-card>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="线程列表" name="threads">
        <div class="thread-list">
          <div v-if="!threadSummaries.length" class="empty">
            暂无线程摘要记录，可先在对话区域与 Agent 交互。
          </div>
          <el-table
            v-else
            :data="threadSummaries"
            size="small"
            border
            style="width: 100%"
          >
            <el-table-column prop="thread_id" label="Thread ID" min-width="220">
              <template #default="scope">
                <el-link
                  type="primary"
                  @click="threadId = scope.row.thread_id; activeTab = 'chat'"
                >
                  {{ scope.row.thread_id }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="last_control_op" label="最近操作" min-width="140" />
            <el-table-column prop="last_control_mode" label="模式" min-width="80" />
            <el-table-column
              prop="last_control_success"
              label="结果"
              min-width="80"
            >
              <template #default="scope">
                <el-tag
                  v-if="scope.row.last_control_success === true"
                  type="success"
                  size="small"
                >
                  成功
                </el-tag>
                <el-tag
                  v-else-if="scope.row.last_control_success === false"
                  type="danger"
                  size="small"
                >
                  失败
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column
              prop="updated_at"
              label="更新时间"
              min-width="160"
            />
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="图表分析" name="charts">
        <div class="charts-panel">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-card shadow="never" header="数据库分析（SQL Agent）">
                <el-form label-width="72px" size="small">
                  <el-form-item label="数据库">
                    <el-input
                      v-model="dbForm.dbName"
                      placeholder="默认 cv_cp，可留空"
                    />
                  </el-form-item>
                  <el-form-item label="问题">
                    <el-input
                      v-model="dbForm.query"
                      type="textarea"
                      :rows="4"
                      placeholder="例如：按城市统计订单总金额和订单数，画一个柱状图"
                    />
                  </el-form-item>
                  <el-form-item>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="dbLoading"
                      :disabled="!agentEnabled || !dbForm.query.trim()"
                      @click="runDbChart"
                    >
                      分析数据库
                    </el-button>
                  </el-form-item>
                </el-form>
                <p v-if="dbResponse?.used_db_name" class="hint">
                  使用数据库：{{ dbResponse.used_db_name }}
                </p>
                <p v-if="dbError" class="error-text">
                  {{ dbError }}
                </p>
              </el-card>

              <el-card shadow="never" header="Excel 分析" style="margin-top: 12px">
                <el-form label-width="72px" size="small">
                  <el-form-item label="文件 ID">
                    <el-input
                      v-model="excelForm.fileId"
                      placeholder="Excel 文件标识（file_id）"
                    />
                  </el-form-item>
                  <el-form-item label="Sheet">
                    <el-input
                      v-model="excelForm.sheetName"
                      placeholder="可选，留空则自动选择"
                    />
                  </el-form-item>
                  <el-form-item label="问题">
                    <el-input
                      v-model="excelForm.query"
                      type="textarea"
                      :rows="4"
                      placeholder="例如：按月份统计销售额和订单数，画一个双折线图"
                    />
                  </el-form-item>
                  <el-form-item>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="excelLoading"
                      :disabled="!agentEnabled || !excelForm.fileId.trim() || !excelForm.query.trim()"
                      @click="runExcelChart"
                    >
                      分析 Excel
                    </el-button>
                  </el-form-item>
                </el-form>
                <p v-if="excelResponse?.used_sheet_name" class="hint">
                  使用 Sheet：{{ excelResponse.used_sheet_name }}
                </p>
                <p v-if="excelError" class="error-text">
                  {{ excelError }}
                </p>
              </el-card>
            </el-col>

            <el-col :span="16">
              <div v-if="dbCharts.length || excelCharts.length" class="charts-display">
                <div v-if="dbCharts.length">
                  <h4 class="charts-title">数据库图表</h4>
                  <div class="charts-strip">
                    <div
                      v-for="c in dbCharts"
                      :key="c.id"
                      class="charts-strip-item"
                    >
                      <AgentChartCard :chart="c" />
                    </div>
                  </div>
                  <div v-if="dbInsight" class="insight">
                    <h5>分析结论</h5>
                    <p>{{ dbInsight }}</p>
                  </div>
                </div>

                <div v-if="excelCharts.length" style="margin-top: 16px">
                  <h4 class="charts-title">Excel 图表</h4>
                  <div class="charts-strip">
                    <div
                      v-for="c in excelCharts"
                      :key="c.id"
                      class="charts-strip-item"
                    >
                      <AgentChartCard :chart="c" />
                    </div>
                  </div>
                  <div v-if="excelInsight" class="insight">
                    <h5>分析结论</h5>
                    <p>{{ excelInsight }}</p>
                  </div>
                </div>
              </div>
              <div v-else class="charts-empty">
                暂无图表结果，可在左侧输入问题并发起分析。
              </div>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-card>
  </div>
</template>

<style scoped>
.agent-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.agent-card {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.agent-card :deep(.el-card__body) {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
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
.agent-tabs {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.agent-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  display: flex;
  min-height: 0;
}
.agent-tabs :deep(.el-tab-pane) {
  flex: 1 1 auto;
  display: flex;
  min-height: 0;
}
.mode-bar {
  margin: 8px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.mode-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.mode-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid transparent;
}
.mode-tab .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
}
.mode-tab .label {
  opacity: .9;
}
.mode-tab.active {
  border-color: #6366f1;
  background: rgba(79, 70, 229, 0.2);
}
.mode-tab.active .dot {
  background: #6366f1;
}
.mode-tab.history-tab .history-dot {
  background: #f97316;
}
.mode-bar .mode-desc {
  flex: 1 1 0;
  text-align: right;
  font-size: 12px;
  opacity: .8;
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
.history-panel-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.8);
  z-index: 2000;
  display: flex;
  justify-content: flex-end;
}
.history-panel-card {
  width: 420px;
  max-width: 100%;
  background: #020617;
  border-left: 1px solid rgba(148, 163, 184, 0.4);
  padding: 12px;
  box-shadow: -4px 0 16px rgba(15, 23, 42, 0.6);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.history-panel-search {
  margin-bottom: 4px;
}
.history-panel-list {
  flex: 1 1 auto;
  overflow: auto;
}
.history-panel-empty {
  font-size: 13px;
  opacity: .8;
  padding: 8px;
}
.agent-main {
  display: flex;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}
.chat-panel {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.messages-container {
  flex: 0 0 auto;
  height: 58vh;
  max-height: 58vh;
  min-height: 120px;
  overflow-y: auto;
  padding: 8px 12px;
  border: 1px solid var(--va-border);
  border-radius: 8px;
  background: var(--va-surface-2, #0f172a);
}
.welcome {
  padding: 12px;
  color: var(--va-text-2);
}
.quick-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
}
.message-row {
  display: flex;
  margin-bottom: 10px;
}
.message-row.user {
  flex-direction: row-reverse;
}
.avatar {
  margin: 0 8px;
}
.avatar-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #fff;
}
.avatar-circle.user { background: #3b82f6; }
.avatar-circle.agent { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.avatar-circle.sys { background: #64748b; }
.bubble {
  max-width: 80%;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.9);
}
.message-row.user .bubble {
  background: rgba(37, 99, 235, 0.25);
}
.bubble .meta {
  font-size: 11px;
  opacity: .7;
  margin-bottom: 2px;
}
.bubble .content {
  white-space: normal;
  font-size: 13px;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.bubble .content p {
  margin: 4px 0;
}
.bubble .content ul,
.bubble .content ol {
  margin: 4px 0;
  padding-left: 18px;
}
.bubble .content li {
  margin: 2px 0;
}
.input-area {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.input-actions .hint {
  opacity: .7;
}
.side-panel {
  flex: 0 0 280px;
  max-width: 320px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow-y: auto;
}
.side-card {
  flex: 0 0 auto;
}
.side-empty {
  font-size: 12px;
  opacity: .8;
}
.control-summary-block {
  font-size: 13px;
}
.control-summary-block .row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.control-summary-block .label {
  opacity: .7;
}
.control-summary-block .value {
  font-family: monospace;
}
.agent-step-list {
  list-style: none;
  padding-left: 0;
  margin: 0;
  font-size: 12px;
}
.agent-step {
  position: relative;
  padding-left: 18px;
  margin-bottom: 6px;
}
.agent-step .line {
  position: absolute;
  left: 6px;
  top: 0;
  bottom: -2px;
  width: 2px;
  background: rgba(148, 163, 184, 0.4);
}
.agent-step .dot {
  position: absolute;
  left: 3px;
  top: 4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6b7280;
}
.agent-step.step-user .dot {
  background: #3b82f6;
}
.agent-step.step-thinking .dot {
  background: #facc15;
}
.agent-step.step-tool .dot {
  background: #22c55e;
}
.agent-step.step-response .dot {
  background: #6366f1;
}
.agent-step .body {
  position: relative;
}
.agent-step .row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}
.agent-step .badge {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.2);
  text-transform: uppercase;
}
.agent-step .tool-name {
  opacity: .8;
}
.agent-step .status {
  margin-left: auto;
  opacity: .8;
}
.agent-step .content {
  white-space: normal;
  opacity: .9;
}
.detail {
  margin-top: 8px;
}
.detail-label {
  font-size: 12px;
  opacity: .7;
  margin-bottom: 2px;
}
.detail-json {
  font-size: 12px;
  max-height: 180px;
  overflow: auto;
}
.tool-step-list {
  list-style: none;
  padding-left: 0;
  margin: 0;
  font-size: 12px;
}
.tool-step-list li {
  margin-bottom: 4px;
}
.tool-step-list .idx {
  display: inline-block;
  width: 28px;
  color: #a5b4fc;
}
.tool-step-list .text {
  white-space: pre-wrap;
}
.thread-list {
  padding: 4px;
  width: 100%;
}
.thread-list .empty {
  font-size: 13px;
  opacity: .8;
  padding: 8px;
}

.charts-panel {
  padding: 4px;
  width: 100%;
}
.charts-display {
  padding: 4px 0;
}
.charts-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}
.charts-strip {
  display: flex;
  flex-wrap: nowrap;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.charts-strip-item {
  flex: 0 0 360px;
  max-width: 480px;
}
.charts-empty {
  font-size: 13px;
  opacity: .8;
  padding: 12px;
}
.hint {
  font-size: 12px;
  opacity: .8;
  margin-top: 4px;
}
.error-text {
  font-size: 12px;
  color: #f97373;
  margin-top: 4px;
}
.insight {
  margin-top: 8px;
  font-size: 13px;
}
.insight h5 {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 600;
}

@media (max-width: 1200px) {
  .agent-main {
    flex-direction: column;
  }
  .side-panel {
    flex: 0 0 auto;
    width: 100%;
    max-width: 100%;
    flex-direction: row;
  }
  .side-card {
    flex: 1 1 0;
  }
}
</style>
