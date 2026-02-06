<template>
  <div class="audit-trace-page" v-loading="loading">
    <header class="trace-head">
      <div class="trace-head-left">
        <div class="trace-breadcrumbs">
          <button class="crumb-link" @click="goBack">Audit Logs</button>
          <el-icon><ArrowRight /></el-icon>
          <span>{{ runDetail?.run?.root_agent_name || 'Agent' }}</span>
          <el-icon><ArrowRight /></el-icon>
          <span class="trace-id">Trace #{{ shortTraceId }}</span>
          <el-tag size="small" class="trace-status" :class="`status-${runStatus}`">{{ statusLabel(runStatus) }}</el-tag>
        </div>
      </div>

      <div class="trace-head-right">
        <div class="trace-metric"><span class="material-symbols-outlined">schedule</span>{{ formatDurationSeconds(runDetail?.run?.duration_seconds) }}</div>
        <div class="trace-metric"><span class="material-symbols-outlined">toll</span>{{ formatNumber(totalTokens) }} Tokens</div>
        <div class="trace-metric"><span class="material-symbols-outlined">payments</span>{{ formatCost(insights?.estimated_cost_usd) }}</div>
      </div>
    </header>

    <div class="trace-body" v-if="runDetail">
      <aside class="trace-left">
        <div class="pane-title">Execution Trace</div>
        <el-tree
          :data="traceTree"
          node-key="span_id"
          :indent="8"
          default-expand-all
          :expand-on-click-node="false"
          highlight-current
          :current-node-key="selectedSpanId || undefined"
          class="trace-tree"
          @node-click="handleNodeClick"
        >
          <template #default="{ data }">
            <div class="trace-node-row" :class="{ active: selectedSpanId === data.span_id }">
              <div class="trace-node-main">
                <span class="trace-node-icon material-symbols-outlined">{{ spanIcon(data.type) }}</span>
                <div class="trace-node-text">
                  <div class="trace-node-name" :title="data.name">{{ wrapNodeName(data.name) }}</div>
                  <div class="trace-node-sub">
                    {{ spanSubtitle(data) }}
                    <span v-if="data.status" class="trace-node-sub-status">{{ statusLabel(data.status) }}</span>
                  </div>
                </div>
              </div>
              <div class="trace-node-tail">
                <span class="trace-node-duration">{{ formatDurationSeconds(data.duration) }}</span>
                <span class="trace-node-status material-symbols-outlined" :class="`status-${normalizeStatus(data.status)}`">
                  {{ statusIcon(data.status) }}
                </span>
              </div>
            </div>
          </template>
        </el-tree>
      </aside>

      <section class="trace-center">
        <el-tabs v-model="activeTab" class="trace-tabs">
          <el-tab-pane label="Inputs" name="inputs">
            <div class="tab-scroll">
              <h2 class="tab-title">{{ selectedSpan?.name || runDetail.run.root_agent_name || 'Run Input' }}</h2>
              <p class="tab-desc">Input context and normalized payload for the selected execution step.</p>

              <el-card class="prompt-card" shadow="never">
                <template #header>
                  <div class="card-head">
                    <span>SYSTEM / INPUT PREVIEW</span>
                    <el-button text size="small" :icon="DocumentCopy" @click="copyText(inputPreview)">Copy</el-button>
                  </div>
                </template>
                <pre class="plain-block">{{ inputPreview || 'No input payload available.' }}</pre>
              </el-card>

              <div class="dual-grid">
                <el-card shadow="never" class="json-card">
                  <template #header>
                    <div class="card-head">
                      <span>Input JSON</span>
                      <span>{{ inputPreview.length }} chars</span>
                    </div>
                  </template>
                  <pre class="json-block">{{ prettyJson(inputPreview) }}</pre>
                </el-card>

                <el-card shadow="never" class="json-card">
                  <template #header>
                    <div class="card-head">
                      <span>Output JSON</span>
                      <span>{{ outputPreview.length }} chars</span>
                    </div>
                  </template>
                  <pre class="json-block">{{ prettyJson(outputPreview) }}</pre>
                </el-card>
              </div>

              <div class="meta-grid">
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Model</div><div class="mini-value">{{ insights?.model_name || 'N/A' }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Action</div><div class="mini-value">{{ actionLabel(runDetail.run.action_type) }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Token Source</div><div class="mini-value">{{ (runDetail.run.token_source || 'none').toUpperCase() }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Environment</div><div class="mini-value">{{ insights?.metadata?.environment || 'prod' }}</div></el-card>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="Outputs" name="outputs">
            <div class="tab-scroll">
              <div class="output-head">
                <h2>Response Content</h2>
                <el-segmented
                  v-model="outputViewMode"
                  :options="[
                    { label: 'JSON', value: 'json' },
                    { label: 'Markdown', value: 'markdown' },
                    { label: 'Raw', value: 'raw' }
                  ]"
                />
              </div>

              <el-card class="output-card" shadow="never">
                <pre class="json-block" :class="{ 'wrap-output': outputWrapText }" v-if="outputViewMode === 'json'">{{ filteredOutputJson }}</pre>
                <pre class="plain-block output-markdown" :class="{ 'wrap-output': outputWrapText }" v-else-if="outputViewMode === 'markdown'">{{ summarizeOutput(outputPreview) }}</pre>
                <pre class="plain-block output-raw" :class="{ 'wrap-output': outputWrapText }" v-else>{{ outputPreview || 'No output payload available.' }}</pre>
              </el-card>

              <el-card class="summary-card" shadow="never">
                <h3>Executive Summary</h3>
                <p>{{ summarizeOutput(outputPreview) }}</p>
              </el-card>
            </div>
          </el-tab-pane>

          <el-tab-pane label="Metadata" name="metadata">
            <div class="tab-scroll">
              <div class="meta-top-row">
                <div>
                  <h2 class="tab-title">Trace Metadata</h2>
                  <p class="tab-desc">Full configuration and context details for the current execution step.</p>
                </div>
                <div class="meta-top-actions">
                  <el-button class="meta-btn" :icon="Download" @click="exportTraceData">JSON</el-button>
                  <el-button class="meta-btn" @click="copyText((insights?.metadata?.tags || []).join(', '), 'Tags copied')">Edit Tags</el-button>
                </div>
              </div>

              <div class="meta-section">
                <h3>Model Configuration</h3>
                <div class="meta-grid five">
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Model Name</div><div class="mini-value">{{ insights?.model_name || 'N/A' }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Prompt Tokens</div><div class="mini-value">{{ formatNumber(runDetail.run.prompt_tokens) }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Completion Tokens</div><div class="mini-value">{{ formatNumber(runDetail.run.completion_tokens) }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Total Tokens</div><div class="mini-value">{{ formatNumber(runDetail.run.total_tokens) }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Cost</div><div class="mini-value">{{ formatCost(insights?.estimated_cost_usd) }}</div></el-card>
                </div>
              </div>

              <div class="meta-section">
                <h3>Infrastructure & Runtime</h3>
                <div class="meta-grid four">
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Request ID</div><div class="mini-value mono">{{ runDetail.run.request_id }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Conversation ID</div><div class="mini-value mono">{{ insights?.metadata?.conversation_id || '-' }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Initiator</div><div class="mini-value">{{ insights?.metadata?.initiator || runDetail.run.initiator || 'System' }}</div></el-card>
                  <el-card shadow="never" class="mini-meta"><div class="mini-label">Environment</div><div class="mini-value">{{ insights?.metadata?.environment || 'prod' }}</div></el-card>
                </div>
              </div>

              <div class="meta-section">
                <h3>Custom Metadata Tags</h3>
                <div class="tags-wrap">
                  <el-tag
                    v-for="tag in insights?.metadata?.tags || []"
                    :key="tag"
                    type="info"
                    effect="plain"
                    round
                  >
                    {{ tag }}
                  </el-tag>
                  <el-empty v-if="!(insights?.metadata?.tags || []).length" description="No tags" :image-size="56" />
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="Stats" name="stats">
            <div class="tab-scroll">
              <h2 class="tab-title">Trace Statistics</h2>
              <p class="tab-desc">Performance breakdown and resource utilization for this trace.</p>

              <div class="stats-kpis">
                <el-card shadow="never" class="mini-meta"><div class="mini-label">TTFT</div><div class="mini-value">{{ formatMs(insights?.stats?.ttft_ms) }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Cost / Request</div><div class="mini-value">{{ formatCost(insights?.estimated_cost_usd) }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Throughput</div><div class="mini-value">{{ formatTps(insights?.stats?.throughput_tps) }}</div></el-card>
                <el-card shadow="never" class="mini-meta"><div class="mini-label">Context Window</div><div class="mini-value">{{ formatPct(insights?.stats?.context_window_utilization_pct) }}</div></el-card>
              </div>

              <el-card shadow="never" class="breakdown-card">
                <template #header>
                  <div class="card-head"><span>Latency Breakdown</span><span>Total: {{ formatMs(latency.total) }}</span></div>
                </template>
                <div class="stack-bar">
                  <div class="seg network" :style="{ width: `${latencyPct.network}%` }">Network ({{ formatMs(latency.network) }})</div>
                  <div class="seg inference" :style="{ width: `${latencyPct.inference}%` }">Inference ({{ formatMs(latency.inference) }})</div>
                  <div class="seg thinking" :style="{ width: `${latencyPct.thinking}%` }">Thinking ({{ formatMs(latency.thinking) }})</div>
                </div>
              </el-card>

              <el-card shadow="never" class="breakdown-card">
                <template #header>
                  <div class="card-head"><span>Token Usage</span><span>{{ formatNumber(totalTokens) }}</span></div>
                </template>
                <div class="token-usage-grid">
                  <div class="token-bars">
                    <div class="token-row">
                      <span>Prompt Tokens</span>
                      <span>{{ formatNumber(runDetail.run.prompt_tokens) }}</span>
                    </div>
                    <el-progress :show-text="false" :percentage="tokenPct.prompt" color="#0ea5e9" />
                    <div class="token-row">
                      <span>Completion Tokens</span>
                      <span>{{ formatNumber(runDetail.run.completion_tokens) }}</span>
                    </div>
                    <el-progress :show-text="false" :percentage="tokenPct.completion" color="#22d3ee" />
                  </div>

                  <div class="token-chart" aria-hidden="true">
                    <div class="token-column prompt" :style="{ height: `${Math.max(18, tokenPct.prompt)}%` }">
                      <span>PROMPT</span>
                    </div>
                    <div class="token-column completion" :style="{ height: `${Math.max(18, tokenPct.completion)}%` }">
                      <span>COMP.</span>
                    </div>
                  </div>
                </div>
              </el-card>

              <el-card shadow="never" class="resource-card">
                <template #header><div class="card-head"><span>Resource Details</span></div></template>
                <el-table :data="insights?.resource_details || []" class="resource-table" empty-text="No resources">
                  <el-table-column prop="resource" label="Resource" min-width="240" />
                  <el-table-column prop="status" label="Status" width="130">
                    <template #default="{ row }">
                      <el-tag size="small" effect="plain" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="duration_ms" label="Duration" width="120" align="right">
                    <template #default="{ row }">{{ formatMs(row.duration_ms) }}</template>
                  </el-table-column>
                </el-table>
              </el-card>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>

      <aside class="trace-right">
        <template v-if="activeTab === 'outputs'">
          <h3>Performance</h3>
          <el-card shadow="never" class="side-card">
            <div class="side-card-label">Output Token Count</div>
            <div class="side-card-value">{{ formatNumber(outputTokenCount) }} <span>Tokens</span></div>
            <el-progress :show-text="false" :percentage="outputTokenPct" color="#25d1f4" />
          </el-card>

          <el-card shadow="never" class="side-card">
            <div class="side-card-label">Finish Reason</div>
            <div class="side-card-value with-icon">
              <span class="material-symbols-outlined">check_circle</span>
              <span>{{ finishReason }}</span>
            </div>
          </el-card>

          <h3 class="side-subtitle">View Options</h3>
          <div class="switch-list">
            <div class="switch-row">
              <span>Show Hidden Keys</span>
              <el-switch v-model="outputShowHidden" />
            </div>
            <div class="switch-row">
              <span>Pretty Print JSON</span>
              <el-switch v-model="outputPrettyJson" />
            </div>
            <div class="switch-row">
              <span>Wrap Text</span>
              <el-switch v-model="outputWrapText" />
            </div>
          </div>

          <h3 class="side-subtitle">Filter Output Keys</h3>
          <div class="filter-key-wrap">
            <el-tag
              v-for="key in outputKeyFilters"
              :key="key"
              closable
              effect="plain"
              @close="removeOutputFilterKey(key)"
            >
              {{ key }}
            </el-tag>
            <div class="filter-key-add">
              <el-input v-model="outputKeyInput" size="small" placeholder="Add key" @keyup.enter="addOutputFilterKey" />
              <el-button text @click="addOutputFilterKey">+ Add Key</el-button>
            </div>
          </div>
        </template>

        <template v-else-if="activeTab === 'stats'">
          <h3>Quick Actions</h3>
          <div class="summary-grid">
            <div class="summary-item"><span>Trace ID</span><code>{{ runDetail.run.request_id }}</code></div>
            <div class="summary-item"><span>Timestamp</span><b>{{ formatDate(runDetail.run.time) }}</b></div>
          </div>
          <div class="summary-actions">
            <el-button type="primary" class="full-btn action-primary" :icon="Download" @click="exportTraceData">Export Data</el-button>
            <el-button class="full-btn action-secondary" :icon="Share" @click="shareTraceLink">Share Trace</el-button>
            <el-button class="full-btn action-danger" :icon="Warning" @click="copyDatasetSample">Add to Dataset</el-button>
          </div>
        </template>

        <template v-else>
          <h3>Trace Summary</h3>
          <div class="summary-grid">
            <div class="summary-item"><span>Trace ID</span><code>{{ runDetail.run.request_id }}</code></div>
            <div class="summary-item"><span>Timestamp</span><b>{{ formatDate(runDetail.run.time) }}</b></div>
            <div class="summary-item"><span>Status</span><b>{{ statusLabel(runStatus) }}</b></div>
            <div class="summary-item"><span>Action</span><b>{{ actionLabel(runDetail.run.action_type) }}</b></div>
          </div>

          <div class="summary-block">
            <h4>Token Usage Break-down</h4>
            <div class="summary-row"><span>Prompt ({{ formatNumber(runDetail.run.prompt_tokens) }})</span><span>{{ tokenPct.prompt.toFixed(1) }}%</span></div>
            <el-progress :show-text="false" :percentage="tokenPct.prompt" color="#25d1f4" />
            <div class="summary-row"><span>Completion ({{ formatNumber(runDetail.run.completion_tokens) }})</span><span>{{ tokenPct.completion.toFixed(1) }}%</span></div>
            <el-progress :show-text="false" :percentage="tokenPct.completion" color="#60a5fa" />
          </div>

          <div class="summary-actions">
            <el-button type="primary" class="full-btn action-primary" :icon="Download" @click="exportTraceData">Export Data</el-button>
            <el-button class="full-btn action-secondary" :icon="Share" @click="shareTraceLink">Share Trace</el-button>
            <el-button class="full-btn action-danger" :icon="Warning" @click="copyDatasetSample">Add to Dataset</el-button>
          </div>
        </template>
      </aside>
    </div>

    <div v-else class="trace-empty">
      <el-empty description="Trace not found" />
      <el-button type="primary" @click="goBack">Back to Audit Logs</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, DocumentCopy, Download, Share, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import apiClient, { type AuditRunDetail } from '@/api/client'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const runDetail = ref<AuditRunDetail | null>(null)
const activeTab = ref<'inputs' | 'outputs' | 'metadata' | 'stats'>('inputs')
const outputViewMode = ref<'json' | 'markdown' | 'raw'>('json')
const selectedSpanId = ref<string | null>(null)
const outputShowHidden = ref(false)
const outputPrettyJson = ref(true)
const outputWrapText = ref(false)
const outputKeyInput = ref('')
const outputKeyFilters = ref<string[]>(['message', 'usage'])

const insights = computed(() => runDetail.value?.insights)
const runStatus = computed(() => normalizeStatus(runDetail.value?.run?.status))
const shortTraceId = computed(() => runDetail.value?.run?.request_id.slice(0, 8) || '-')
const totalTokens = computed(() => runDetail.value?.run?.total_tokens || 0)
const outputTokenCount = computed(() => runDetail.value?.run?.completion_tokens || 0)
const outputTokenPct = computed(() => {
  if (!totalTokens.value) return 0
  return Math.max(0, Math.min(100, (outputTokenCount.value / totalTokens.value) * 100))
})

const traceTree = computed(() => {
  const spans = runDetail.value?.spans || []
  if (!spans.length) return [] as any[]

  const map = new Map<string, any>()
  spans.forEach((span) => {
    map.set(span.span_id, { ...span, children: [] as any[] })
  })

  const roots: any[] = []
  map.forEach((node) => {
    if (node.parent_span_id && map.has(node.parent_span_id)) {
      map.get(node.parent_span_id).children.push(node)
    } else {
      roots.push(node)
    }
  })

  return roots
})

const selectedSpan = computed(() => {
  if (!selectedSpanId.value) return null
  return (runDetail.value?.spans || []).find((s) => s.span_id === selectedSpanId.value) || null
})

const inputPreview = computed(() => {
  const bySpan = selectedSpanEvents.value.find((e) => e.payload?.messages_digest || e.payload?.inputs_digest || e.payload?.input_digest)
  return (
    (bySpan?.payload?.messages_digest as string) ||
    (bySpan?.payload?.inputs_digest as string) ||
    (bySpan?.payload?.input_digest as string) ||
    (insights.value?.input_preview as string) ||
    ''
  )
})

const outputPreview = computed(() => {
  const bySpan = [...selectedSpanEvents.value]
    .reverse()
    .find((e) => e.payload?.generations_digest || e.payload?.outputs_digest || e.payload?.output_digest)
  return (
    (bySpan?.payload?.generations_digest as string) ||
    (bySpan?.payload?.outputs_digest as string) ||
    (bySpan?.payload?.output_digest as string) ||
    (insights.value?.output_preview as string) ||
    ''
  )
})

const parsedOutput = computed(() => {
  const raw = outputPreview.value
  if (!raw) return null
  try {
    return JSON.parse(raw) as Record<string, any>
  } catch {
    return null
  }
})

function stripHiddenKeys(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => stripHiddenKeys(item))
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (k.startsWith('_')) continue
      out[k] = stripHiddenKeys(v)
    }
    return out
  }
  return value
}

const filteredOutputJson = computed(() => {
  const parsed = parsedOutput.value
  if (!parsed) {
    if (!outputPreview.value) return '{}'
    return outputPrettyJson.value ? prettyJson(outputPreview.value) : outputPreview.value
  }

  let nextPayload: Record<string, unknown> = parsed
  if (!outputShowHidden.value) {
    nextPayload = stripHiddenKeys(nextPayload) as Record<string, unknown>
  }

  if (outputKeyFilters.value.length) {
    const subset: Record<string, unknown> = {}
    for (const key of outputKeyFilters.value) {
      if (key in nextPayload) subset[key] = nextPayload[key]
    }
    if (Object.keys(subset).length) {
      nextPayload = subset
    }
  }

  if (outputPrettyJson.value) {
    return JSON.stringify(nextPayload, null, 2)
  }
  return JSON.stringify(nextPayload)
})

const finishReason = computed(() => {
  const parsed = parsedOutput.value
  const reason =
    parsed?.choices?.[0]?.finish_reason ||
    parsed?.finish_reason ||
    parsed?.status ||
    'stop'
  return String(reason).replace(/_/g, ' ')
})

const selectedSpanEvents = computed(() => {
  if (!selectedSpanId.value) return runDetail.value?.recent_events || []
  return (runDetail.value?.recent_events || []).filter((e) => e.span_id === selectedSpanId.value)
})

const latency = computed(() => {
  const v = insights.value?.latency_breakdown_ms || {}
  return {
    network: Number(v.network || 0),
    inference: Number(v.inference || 0),
    thinking: Number(v.thinking || 0),
    total: Number(v.total || 0),
  }
})

const latencyPct = computed(() => {
  const total = latency.value.total || 1
  return {
    network: Math.max(0, Math.min(100, (latency.value.network / total) * 100)),
    inference: Math.max(0, Math.min(100, (latency.value.inference / total) * 100)),
    thinking: Math.max(0, Math.min(100, (latency.value.thinking / total) * 100)),
  }
})

const tokenPct = computed(() => {
  const prompt = runDetail.value?.run?.prompt_tokens || 0
  const completion = runDetail.value?.run?.completion_tokens || 0
  const total = prompt + completion
  if (!total) return { prompt: 0, completion: 0 }
  return {
    prompt: (prompt / total) * 100,
    completion: (completion / total) * 100,
  }
})

function spanIcon(type: string) {
  const t = (type || '').toLowerCase()
  if (t === 'llm') return 'auto_awesome'
  if (t === 'tool') return 'handyman'
  if (t === 'node') return 'account_tree'
  if (t === 'job') return 'work'
  if (t === 'job_phase') return 'event'
  return 'hub'
}

function normalizeStatus(status?: string) {
  const s = String(status || '')
    .trim()
    .toLowerCase()
    .replace('-', '_')

  if (['succeeded', 'success', 'completed', 'done'].includes(s)) return 'succeeded'
  if (['failed', 'error', 'errored'].includes(s)) return 'failed'
  if (['interrupted', 'cancelled', 'canceled', 'paused'].includes(s)) return 'interrupted'
  if (['running', 'in_progress', 'processing', 'started', 'pending', 'queued'].includes(s)) return 'running'
  return s || 'unknown'
}

function statusIcon(status: string) {
  const s = normalizeStatus(status)
  if (s === 'succeeded') return 'check_circle'
  if (s === 'failed') return 'error'
  if (s === 'interrupted') return 'pause_circle'
  if (s === 'running') return 'progress_activity'
  return 'help'
}

function statusLabel(status?: string) {
  const s = normalizeStatus(status)
  if (s === 'succeeded') return 'SUCCESS'
  if (s === 'failed') return 'FAILED'
  if (s === 'interrupted') return 'INTERRUPTED'
  if (s === 'running') return 'RUNNING'
  return (status || 'UNKNOWN').toUpperCase()
}

function actionLabel(action?: string) {
  const a = (action || '').toLowerCase()
  if (a === 'llm') return 'LLM CALL'
  if (a === 'tool') return 'TOOL USE'
  if (a === 'interrupt') return 'INTERRUPT'
  if (a === 'job') return 'JOB'
  return 'CHAIN'
}

function spanSubtitle(span: { type?: string; meta?: Record<string, any> }) {
  const spanType = (span.type || 'step').toLowerCase()
  const humanType = spanType.replace(/_/g, ' ')
  const meta = span.meta || {}
  const metaTokens = Number(meta.total_tokens || meta.tokens || meta.output_tokens || 0)
  if (Number.isFinite(metaTokens) && metaTokens > 0) {
    return `${humanType} • ${formatNumber(metaTokens)} tokens`
  }
  return humanType
}

function wrapNodeName(name?: string, maxLen: number = 26) {
  const text = String(name || '')
  const chars = Array.from(text)
  if (chars.length <= maxLen) return text

  const lines: string[] = []
  for (let i = 0; i < chars.length; i += maxLen) {
    lines.push(chars.slice(i, i + maxLen).join(''))
  }
  return lines.join('\n')
}

function statusTagType(status?: string) {
  const s = normalizeStatus(status)
  if (s === 'succeeded') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'interrupted') return 'warning'
  if (s === 'running') return 'info'
  return 'info'
}

function formatDate(value?: string) {
  if (!value) return '-'
  return dayjs(value).format('MMM D, HH:mm:ss')
}

function formatNumber(value?: number) {
  return new Intl.NumberFormat('en-US').format(value || 0)
}

function formatDurationSeconds(seconds?: number | null) {
  if (seconds == null) return '--'
  if (seconds < 1) return `${Math.max(1, Math.round(seconds * 1000))}ms`
  if (seconds < 10) return `${seconds.toFixed(2)}s`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.round(seconds)}s`
}

function formatMs(ms?: number | null) {
  if (ms == null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatTps(v?: number | null) {
  if (v == null) return '--'
  return `${v.toFixed(2)} t/s`
}

function formatPct(v?: number | null) {
  if (v == null) return '--'
  return `${v.toFixed(2)}%`
}

function formatCost(v?: number | null) {
  if (v == null) return 'N/A'
  return `$${v.toFixed(6)}`
}

function prettyJson(raw: string) {
  if (!raw) return '{}'
  try {
    const parsed = JSON.parse(raw)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return raw
  }
}

function summarizeOutput(raw: string) {
  if (!raw) return 'No output data available for this step.'
  const text = raw.replace(/\s+/g, ' ').trim()
  return text.length > 320 ? `${text.slice(0, 320)}...` : text
}

function addOutputFilterKey() {
  const key = outputKeyInput.value.trim()
  if (!key) return
  if (!outputKeyFilters.value.includes(key)) {
    outputKeyFilters.value = [...outputKeyFilters.value, key]
  }
  outputKeyInput.value = ''
}

function removeOutputFilterKey(key: string) {
  outputKeyFilters.value = outputKeyFilters.value.filter((item) => item !== key)
}

async function copyText(value: string, successMessage: string = 'Copied') {
  try {
    await navigator.clipboard.writeText(value || '')
    ElMessage.success(successMessage)
  } catch {
    ElMessage.warning('Copy failed')
  }
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function exportTraceData() {
  if (!runDetail.value) {
    ElMessage.warning('No trace data to export')
    return
  }
  const traceId = runDetail.value.run.request_id || 'trace'
  downloadJson(`audit-trace-${traceId}.json`, runDetail.value)
  ElMessage.success('Trace exported')
}

async function shareTraceLink() {
  await copyText(window.location.href, 'Trace link copied')
}

async function copyDatasetSample() {
  if (!runDetail.value) {
    ElMessage.warning('No trace data available')
    return
  }

  const sample = {
    request_id: runDetail.value.run.request_id,
    root_agent_name: runDetail.value.run.root_agent_name || null,
    status: runDetail.value.run.status,
    action_type: runDetail.value.run.action_type,
    input_preview: inputPreview.value || null,
    output_preview: outputPreview.value || null,
    metadata: runDetail.value.insights?.metadata || {},
  }

  await copyText(JSON.stringify(sample, null, 2), 'Dataset sample copied')
}

function handleNodeClick(data: any) {
  selectedSpanId.value = data?.span_id || null
}

function goBack() {
  router.push('/audit')
}

async function loadDetail() {
  const id = route.params.requestId as string
  if (!id) {
    runDetail.value = null
    return
  }

  loading.value = true
  try {
    const detail = await apiClient.getAuditRunSummary(id)
    runDetail.value = detail
    selectedSpanId.value = detail.spans?.[0]?.span_id || null
  } catch (error) {
    console.error('Failed to load audit trace detail', error)
    runDetail.value = null
  } finally {
    loading.value = false
  }
}

watch(() => route.params.requestId, loadDetail)

onMounted(loadDetail)
</script>

<style scoped>
.audit-trace-page {
  height: 100%;
  background: #fbfdff;
  color: #0f181a;
  font-family: 'Noto Sans', var(--font-sans);
  overflow: hidden;
}

.trace-head {
  height: 56px;
  border-bottom: 1px solid #dfeaf0;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  gap: 12px;
}

.trace-breadcrumbs {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #60758a;
  font-weight: 600;
}

.crumb-link {
  border: none;
  background: transparent;
  padding: 0;
  color: #25bce4;
  font-weight: 700;
  cursor: pointer;
}

.trace-id {
  font-weight: 800;
  color: #111e2f;
}

.trace-status {
  margin-left: 4px;
  border: none;
  font-weight: 800;
}

.trace-status.status-succeeded {
  background: #e8fff3;
  color: #0aaf73;
}

.trace-status.status-failed {
  background: #ffe8ef;
  color: #f1446b;
}

.trace-status.status-interrupted,
.trace-status.status-cancelled {
  background: #fff5dd;
  color: #da8b00;
}

.trace-status.status-running {
  background: #e7f8ff;
  color: #0a9dd7;
}

.trace-head-right {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  color: #586d82;
  font-size: 13px;
  font-weight: 700;
}

.trace-metric {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.trace-metric .material-symbols-outlined {
  font-size: 16px;
}

.trace-body {
  height: calc(100% - 56px);
  display: grid;
  grid-template-columns: 420px minmax(560px, 1fr) 320px;
  background: #ffffff;
}

.trace-left {
  border-right: 1px solid #e0ebf1;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-title {
  padding: 14px 14px 10px;
  border-bottom: 1px solid #e0ebf1;
  font-size: 12px;
  font-weight: 800;
  color: #7a8ea2;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.trace-tree {
  padding: 8px 10px;
  overflow-x: auto;
  overflow-y: auto;
  flex: 1;
  --el-tree-node-hover-bg-color: #ffffff;
}

.trace-tree :deep(.el-tree) {
  width: max-content;
  min-width: 100%;
}

.trace-tree :deep(.el-tree-node) {
  position: relative;
}

.trace-tree :deep(.el-tree-node__content) {
  height: auto;
  padding: 2px 0;
  position: relative;
  width: 100%;
  min-width: 0;
}

.trace-tree :deep(.el-tree-node__children) {
  margin-left: 0;
  padding-left: 2px;
  position: relative;
}

.trace-tree :deep(.el-tree-node__children::before) {
  content: '';
  position: absolute;
  top: 2px;
  bottom: 12px;
  left: 1px;
  border-left: 1px solid #d8e5ef;
}

.trace-tree :deep(.el-tree-node__content::before) {
  content: '';
  position: absolute;
  left: -2px;
  top: 50%;
  width: 2px;
  border-top: 1px solid #d8e5ef;
}

.trace-node-row {
  width: max-content;
  min-width: 100%;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.trace-node-row.active {
  border-color: #24c5eb;
  background: #ffffff;
  box-shadow: 0 0 0 1px rgba(36, 197, 235, 0.2);
}

.trace-node-main {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: max-content;
}

.trace-node-text {
  min-width: 0;
}

.trace-node-icon {
  font-size: 18px;
  color: #7c93a8;
}

.trace-node-name {
  font-size: 14px;
  font-weight: 700;
  color: #15273a;
  white-space: pre-wrap;
  overflow: visible;
  text-overflow: clip;
  max-width: none;
  line-height: 1.25;
}

.trace-node-sub {
  font-size: 11px;
  color: #7890a4;
  text-transform: lowercase;
}

.trace-node-sub-status {
  margin-left: 6px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 700;
  color: #5b748f;
}

.trace-node-tail {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: 8px;
  position: sticky;
  right: 0;
  z-index: 1;
  padding-left: 14px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0) 0%, #ffffff 14px);
}

.trace-node-duration {
  font-size: 12px;
  color: #7f96aa;
  font-weight: 700;
}

.trace-node-status {
  font-size: 14px;
  font-variation-settings: 'FILL' 1;
}

.trace-node-status.status-succeeded { color: #0fb87a; }
.trace-node-status.status-failed { color: #f1446b; }
.trace-node-status.status-interrupted,
.trace-node-status.status-cancelled { color: #da8b00; }
.trace-node-status.status-running { color: #0a9dd7; }

.trace-center {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e0ebf1;
}

.trace-tabs {
  height: 100%;
}

.trace-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 18px;
  border-bottom: 1px solid #e3edf3;
}

.trace-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.trace-tabs :deep(.el-tabs__active-bar) {
  background: #25d1f4;
  height: 3px;
  border-radius: 999px;
}

.trace-tabs :deep(.el-tabs__item) {
  font-size: 34px;
  font-weight: 700;
  height: 58px;
  line-height: 58px;
  color: #5c7289;
  font-family: 'Space Grotesk', var(--font-sans);
}

.trace-tabs :deep(.el-tabs__item.is-active) {
  color: #111f31;
}

.trace-tabs :deep(.el-tabs__content) {
  height: calc(100% - 59px);
}

.trace-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.tab-scroll {
  height: 100%;
  overflow-y: auto;
  padding: 18px;
  background: #ffffff;
}

.tab-title {
  margin: 0;
  font-size: 50px;
  line-height: 1.04;
  letter-spacing: -0.02em;
  color: #0f1b2d;
  font-family: 'Space Grotesk', var(--font-sans);
}

.tab-desc {
  margin: 8px 0 16px;
  color: #627991;
  font-size: 15px;
}

.prompt-card,
.json-card,
.summary-card,
.breakdown-card,
.resource-card,
.mini-meta {
  border: 1px solid #dfeaf0;
  border-radius: 14px;
}

.prompt-card,
.breakdown-card,
.resource-card,
.summary-card {
  margin-bottom: 14px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  font-weight: 800;
  color: #6f8499;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.plain-block,
.json-block {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.56;
}

.json-block {
  background: radial-gradient(circle at 15% 15%, #111f39 0%, #08101d 72%);
  color: #d9eef7;
  border-radius: 12px;
  padding: 14px;
  overflow-x: auto;
}

.output-markdown,
.output-raw {
  color: #d7e6f5;
  white-space: pre;
  overflow-x: auto;
}

.wrap-output {
  white-space: pre-wrap !important;
}

.dual-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.meta-grid.five {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.meta-grid.four {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.mini-meta :deep(.el-card__body) {
  padding: 12px;
}

.mini-label {
  font-size: 11px;
  font-weight: 800;
  color: #7a8ea2;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mini-value {
  margin-top: 6px;
  font-size: 24px;
  font-family: 'Space Grotesk', var(--font-sans);
  font-weight: 800;
  color: #101d2f;
  line-height: 1.15;
  word-break: break-word;
}

.mini-value.mono {
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
}

.meta-section {
  margin-bottom: 16px;
}

.meta-top-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.meta-top-actions {
  display: inline-flex;
  gap: 10px;
}

.meta-btn {
  height: 42px;
  border-radius: 12px;
  border: 1px solid #d9e7f0;
  color: #00b5e5;
  font-weight: 700;
}

.meta-section h3,
.summary-card h3,
.breakdown-card h3 {
  margin: 0 0 10px;
  font-size: 18px;
  font-family: 'Space Grotesk', var(--font-sans);
  color: #142538;
}

.tags-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.output-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.output-head h2 {
  margin: 0;
  font-size: 24px;
  font-family: 'Space Grotesk', var(--font-sans);
}

.output-head :deep(.el-segmented) {
  --el-segmented-item-selected-bg-color: #6478ff;
  --el-segmented-item-selected-color: #ffffff;
  border: 1px solid #d8e6ef;
  border-radius: 10px;
  padding: 2px;
  background: #f9fcff;
}

.output-head :deep(.el-segmented__item) {
  color: #5f84a0;
  font-weight: 700;
}

.output-head :deep(.el-segmented__item.is-selected) {
  box-shadow: none;
}

.output-card {
  border-radius: 14px;
  border: 1px solid #dbe7ee;
  background: #0d1117;
  margin-bottom: 14px;
}

.output-card :deep(.el-card__body) {
  padding: 12px;
}

.stats-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.stack-bar {
  height: 44px;
  border-radius: 10px;
  background: #eef4f8;
  display: flex;
  overflow: hidden;
}

.seg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
  min-width: 0;
  overflow: hidden;
}

.seg.network { background: #0ea5e9; }
.seg.inference { background: #25d1f4; }
.seg.thinking { background: #94a3b8; }

.token-bars {
  display: grid;
  gap: 8px;
}

.token-usage-grid {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) 240px;
  gap: 18px;
  align-items: end;
}

.token-chart {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 14px;
  height: 140px;
  border-left: 1px solid #dbe7ef;
  border-bottom: 1px solid #dbe7ef;
  padding: 12px 10px 0 18px;
}

.token-column {
  width: 88px;
  border-radius: 8px 8px 0 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  min-height: 22px;
  transition: height 0.25s ease;
}

.token-column.prompt {
  background: #11a8ed;
}

.token-column.completion {
  background: #22d3ee;
}

.token-column span {
  color: #6f87a0;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: -24px;
}

.token-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #38526a;
  font-size: 13px;
  font-weight: 700;
}

.resource-table :deep(th.el-table__cell) {
  font-size: 11px;
  font-weight: 800;
  color: #6f869b;
  letter-spacing: 0.08em;
}

.trace-right {
  background: #ffffff;
  padding: 16px;
  overflow-y: auto;
  border-left: 1px solid #e0ebf1;
}

.trace-right h3 {
  margin: 0 0 14px;
  font-size: 14px;
  color: #7b90a4;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.side-subtitle {
  margin-top: 16px;
}

.side-card {
  border: 1px solid #deebf3;
  border-radius: 14px;
  margin-bottom: 12px;
}

.side-card :deep(.el-card__body) {
  padding: 14px;
}

.side-card-label {
  font-size: 12px;
  font-weight: 800;
  color: #6f869b;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
}

.side-card-value {
  font-size: 42px;
  line-height: 1;
  font-weight: 800;
  font-family: 'Space Grotesk', var(--font-sans);
  color: #0f1f31;
  margin-bottom: 10px;
}

.side-card-value span {
  font-size: 20px;
  font-family: 'Noto Sans', var(--font-sans);
  color: #8aa1b5;
  font-weight: 700;
}

.side-card-value.with-icon {
  font-size: 30px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 0;
}

.side-card-value.with-icon .material-symbols-outlined {
  font-size: 20px;
  color: #0abf7e;
  font-variation-settings: 'FILL' 1;
}

.switch-list {
  display: grid;
  gap: 10px;
}

.switch-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  color: #3d5a76;
  font-weight: 700;
}

.switch-row :deep(.el-switch__core) {
  border-radius: 12px;
  min-width: 40px;
}

.switch-row :deep(.el-switch.is-checked .el-switch__core) {
  background: #25d1f4;
  border-color: #25d1f4;
}

.filter-key-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter-key-wrap :deep(.el-tag) {
  border-radius: 10px;
  border-color: #d8e5ef;
  color: #3e5a77;
}

.filter-key-add {
  width: 100%;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.filter-key-add :deep(.el-input__wrapper) {
  border-radius: 10px;
  border: 1px solid #d9e7f0;
  box-shadow: none;
}

.summary-grid {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #597087;
}

.summary-item b,
.summary-item code {
  color: #0f1f31;
  font-weight: 700;
}

.summary-item code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  background: #f2f7fa;
  padding: 2px 6px;
  border-radius: 6px;
}

.summary-block {
  border-top: 1px solid #e0ebf1;
  border-bottom: 1px solid #e0ebf1;
  padding: 12px 0;
  margin-bottom: 14px;
}

.summary-block h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #2c4760;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #5f748a;
  font-size: 12px;
  margin-bottom: 4px;
}

.summary-actions {
  display: grid;
  gap: 10px;
}

.full-btn {
  width: 100%;
  height: 46px;
  border-radius: 12px;
  font-weight: 800;
}

.full-btn.action-primary {
  background: #06122a !important;
  border-color: #06122a !important;
  color: #ffffff !important;
}

.full-btn.action-primary:hover {
  transform: none;
  box-shadow: none;
  opacity: 0.96;
}

.full-btn.action-secondary {
  border-color: #d9e7f0;
  color: #0f1f31;
  background: #ffffff;
}

.full-btn.action-danger {
  color: #ef395f;
  border-color: #f4cad4;
  background: #ffffff;
}

.trace-empty {
  height: 100%;
  display: grid;
  place-content: center;
  gap: 12px;
}

@media (max-width: 1600px) {
  .trace-body {
    grid-template-columns: 360px minmax(480px, 1fr) 300px;
  }

  .trace-tabs :deep(.el-tabs__item) {
    font-size: 26px;
  }

  .tab-title {
    font-size: 38px;
  }

  .stats-kpis,
  .meta-grid.five,
  .meta-grid.four {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .token-usage-grid {
    grid-template-columns: 1fr;
  }

  .token-chart {
    border-left: none;
    justify-content: flex-start;
    padding-left: 0;
  }
}

@media (max-width: 1280px) {
  .trace-body {
    grid-template-columns: 320px 1fr;
  }

  .trace-right {
    display: none;
  }

  .dual-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }

  .meta-top-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .tab-title {
    font-size: 30px;
  }
}

@media (max-width: 900px) {
  .trace-head {
    height: auto;
    padding: 10px 12px;
    flex-direction: column;
    align-items: flex-start;
  }

  .trace-body {
    height: calc(100% - 90px);
    grid-template-columns: 1fr;
  }

  .trace-left {
    display: none;
  }

  .trace-tabs :deep(.el-tabs__item) {
    font-size: 18px;
    height: 46px;
    line-height: 46px;
  }

  .tab-title {
    font-size: 26px;
  }
}
</style>
