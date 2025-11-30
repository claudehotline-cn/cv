<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import MetricsTimeseries from '@/components/analytics/MetricsTimeseries.vue'
import EventsList from '@/components/observability/EventsList.vue'
import { agentApi, isAgentEnabled, type AgentMessage, type AgentControlResult } from '@/api/agent'
// 预览占位：如需实际 WHEP 播放，可引入 WhepPlayer
// import WhepPlayer from '@/widgets/WhepPlayer/WhepPlayer.vue'

const route = useRoute()
const name = computed(() => decodeURIComponent(String(route.params.name||'')))

const agentEnabled = isAgentEnabled()
const pipelineThreadId = computed(() => (name.value ? `pipeline:${name.value}` : ''))
const agentMessages = ref<AgentMessage[]>([])
const agentInput = ref('')
const agentSending = ref(false)
const agentControlResult = ref<AgentControlResult | null>(null)

async function sendToPipelineAgent() {
  if (!agentInput.value.trim()) return
  if (!pipelineThreadId.value) {
    ElMessage.warning('当前页面缺少 pipeline 名称，无法构造线程 ID')
    return
  }
  if (!agentEnabled) {
    ElMessage.info('Agent 已禁用，当前仅展示前端示例 UI。')
    return
  }
  const userMsg: AgentMessage = { role: 'user', content: agentInput.value.trim() }
  agentMessages.value.push(userMsg)
  const payload = {
    messages: [...agentMessages.value],
  }
  agentSending.value = true
  try {
    const resp = await agentApi.invokeThread(pipelineThreadId.value, payload)
    if (resp.message) {
      agentMessages.value.push(resp.message)
    }
    agentControlResult.value = resp.control_result ?? null
    agentInput.value = ''
  } catch (e: any) {
    ElMessage.error(e?.message || '调用 Agent 失败')
  } finally {
    agentSending.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-page-header :content="`Pipeline: ${name}`"/>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="12">
        <el-card shadow="never" class="chart-card" header="Pipeline FPS">
          <MetricsTimeseries metric="pipeline_fps" :range-minutes="30" :pipeline="name"/>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="chart-card" header="Inference P95 Latency">
          <MetricsTimeseries metric="latency_ms_p95" :range-minutes="30" :pipeline="name"/>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="24">
        <el-card shadow="hover" header="最近事件">
          <EventsList :limit="30" :pipeline="name"/>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="24">
        <el-card shadow="never" class="agent-card" header="Agent（当前 Pipeline）">
          <template #header>
            <div class="agent-head">
              <span>Agent（当前 Pipeline）</span>
              <el-tag v-if="!agentEnabled" type="info" size="small">Agent 已禁用</el-tag>
              <el-tag v-else type="success" size="small">
                线程 ID：{{ pipelineThreadId }}
              </el-tag>
            </div>
          </template>
          <div class="agent-chat">
            <div class="agent-messages">
              <div
                v-for="(m, idx) in agentMessages"
                :key="idx"
                class="agent-msg"
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
              <div v-if="agentControlResult" class="agent-control-result">
                <div class="role">ControlResult</div>
                <pre class="content">{{ JSON.stringify(agentControlResult, null, 2) }}</pre>
              </div>
            </div>
            <div class="agent-input-bar">
              <el-input
                v-model="agentInput"
                type="textarea"
                :rows="2"
                placeholder="针对当前 pipeline 询问或下达控制指令，例如：'计划 drain 当前 pipeline。'"
              />
              <div class="agent-actions">
                <el-button
                  type="primary"
                  size="small"
                  :loading="agentSending"
                  :disabled="!agentEnabled"
                  @click="sendToPipelineAgent"
                >
                  发送
                </el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 如需预览流，可启用 WhepPlayer
    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="24">
        <el-card shadow="hover" header="预览（WHEP）">
          <WhepPlayer />
        </el-card>
      </el-col>
    </el-row>
    -->
  </div>
</template>

<style scoped>
.page{ padding: 4px; }
.chart-card{ min-height: 260px; }
.agent-card{
  min-height: 220px;
}
.agent-head{
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.agent-chat{
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.agent-messages{
  max-height: 220px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--va-border);
  border-radius: 4px;
  background: var(--va-surface-2, #0f172a);
}
.agent-msg{
  margin-bottom: 6px;
}
.agent-msg .role{
  font-size: 12px;
  opacity: .7;
}
.agent-msg .content{
  white-space: pre-wrap;
}
.agent-msg.user .role{ color:#3b82f6; }
.agent-msg.assistant .role{ color:#22c55e; }
.agent-control-result{
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--va-border);
}
.agent-control-result .content{
  font-size: 12px;
}
.agent-input-bar{
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}
.agent-actions{
  display: flex;
  justify-content: flex-end;
}
</style>

