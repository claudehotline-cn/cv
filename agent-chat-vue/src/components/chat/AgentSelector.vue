<template>
  <div class="agent-selector">
    <el-dropdown 
      trigger="click" 
      class="agent-dropdown" 
      placement="bottom-start"
      @command="handleCommand"
    >
      <div class="agent-trigger glass-panel-light" :class="{ loading: isLoading }">
        <div class="trigger-content">
          <div class="icon-box">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="agent-info">
            <span class="label">Current Agent</span>
            <span class="value">{{ currentAgent?.name || '选择 Agent' }}</span>
          </div>
        </div>
        <el-icon class="arrow-icon"><ArrowDown /></el-icon>
      </div>

      <template #dropdown>
        <el-dropdown-menu class="agent-menu glass-dropdown">
          <el-dropdown-item
            v-for="agent in agents"
            :key="agent.id"
            :command="agent.id"
            :class="{ active: selectedAgentId === agent.id }"
          >
            <div class="menu-item-content">
              <span>{{ agent.name }}</span>
              <el-tag size="small" :type="agent.type === 'builtin' ? 'success' : 'info'" effect="plain">
                {{ agent.type === 'builtin' ? '内置' : '自定义' }}
              </el-tag>
            </div>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Cpu, ArrowDown } from '@element-plus/icons-vue'
import apiClient from '@/api/client'

interface Agent {
  id: string
  name: string
  type: 'builtin' | 'custom'
  builtin_key?: string
}

const props = defineProps<{
  modelValue?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', agent: Agent): void
}>()

const agents = ref<Agent[]>([])
const selectedAgentId = ref(props.modelValue || '')
const isLoading = ref(false)

const currentAgent = computed(() => 
  agents.value.find(a => a.id === selectedAgentId.value)
)

onMounted(async () => {
  await loadAgents()
})

watch(() => props.modelValue, (newVal) => {
  if (newVal) {
    selectedAgentId.value = newVal
  }
})

async function loadAgents() {
  isLoading.value = true
  try {
    agents.value = await apiClient.listAgents()
    // 默认选中第一个
    if (agents.value.length > 0 && !selectedAgentId.value) {
      handleCommand(agents.value[0].id)
    }
  } catch (e) {
    console.error('Failed to load agents:', e)
  } finally {
    isLoading.value = false
  }
}

function handleCommand(agentId: string) {
  selectedAgentId.value = agentId
  emit('update:modelValue', agentId)
  const agent = agents.value.find(a => a.id === agentId)
  if (agent) {
    emit('change', agent)
  }
}
</script>

<style scoped>
.agent-selector {
  width: 100%;
}

.agent-dropdown {
  width: 100%;
}

.agent-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 12px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.05);
  transition: all 0.2s ease;
}

.agent-trigger:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--accent-primary);
}

.trigger-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-box {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--accent-gradient, linear-gradient(135deg, #6366f1 0%, #a855f7 100%));
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 16px;
}

.agent-info {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.label {
  font-size: 10px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.arrow-icon {
  color: var(--text-secondary);
  font-size: 12px;
}

.menu-item-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 20px;
  min-width: 180px;
}

/* Glass effect for light theme helper */
.glass-panel-light {
  backdrop-filter: blur(8px);
}
</style>
