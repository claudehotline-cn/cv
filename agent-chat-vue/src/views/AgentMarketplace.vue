<template>
  <el-container class="marketplace-layout">
    <el-header class="glass-panel header">
      <div class="header-content">
        <h2>Agent 市场</h2>
        <p class="subtitle">选择一个智能体开始对话</p>
      </div>
    </el-header>

    <el-main>
      <div v-if="isLoading" class="loading-state">
        <el-skeleton :rows="3" animated />
      </div>

      <div v-else class="agent-grid">
        <div 
          v-for="agent in agents" 
          :key="agent.id" 
          class="agent-card glass-panel-light"
          @click="handleSelectAgent(agent)"
        >
          <div class="card-icon" :style="{ background: getGradient(agent.name) }">
            <el-icon><Cpu /></el-icon>
          </div>
          
          <div class="card-content">
            <div class="card-header">
              <h3>{{ agent.name }}</h3>
              <el-tag size="small" :type="agent.type === 'builtin' ? 'success' : 'info'" effect="light">
                {{ agent.type === 'builtin' ? '官方' : '社区' }}
              </el-tag>
            </div>
            
            <p class="description">{{ agent.config?.description || '暂无描述' }}</p>
            
            <div class="card-footer">
              <span class="model-tag">
                <el-icon><Connection /></el-icon>
                {{ agent.config?.model || 'gpt-4o' }}
              </span>
              <el-button type="primary" round size="small" class="action-btn">
                对话 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Cpu, Connection, ArrowRight } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import apiClient from '@/api/client'

const router = useRouter()
const chatStore = useChatStore()

const agents = ref<any[]>([])
const isLoading = ref(false)

onMounted(async () => {
  await loadAgents()
})

async function loadAgents() {
  isLoading.value = true
  try {
    agents.value = await apiClient.listAgents()
  } catch (e) {
    console.error('Failed to load agents', e)
  } finally {
    isLoading.value = false
  }
}

function handleSelectAgent(agent: any) {
  chatStore.setCurrentAgent(agent.id)
  chatStore.createSession(`Chat with ${agent.name}`)
  router.push('/')
}

function getGradient(name: string) {
  const gradients = [
    'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
    'linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%)',
    'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    'linear-gradient(135deg, #10b981 0%, #3b82f6 100%)'
  ]
  const index = name.length % gradients.length
  return gradients[index]
}
</script>

<style scoped>
.marketplace-layout {
  height: 100vh;
  background: var(--bg-primary);
  overflow-y: auto;
}

.header {
  padding: 40px 0;
  height: auto !important;
  background: transparent !important;
  border-bottom: 1px solid var(--border-color);
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

.header h2 {
  font-size: 32px;
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0 0 8px 0;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 16px;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 24px;
  max-width: 1200px;
  margin: 40px auto;
  padding: 0 24px;
}

.agent-card {
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 20px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.agent-card:hover {
  transform: translateY(-4px);
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--accent-primary);
  box-shadow: 0 20px 40px -12px rgba(0, 0, 0, 0.2);
}

.card-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 24px;
  flex-shrink: 0;
}

.card-content {
  flex: 1;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.description {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 16px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
}

.model-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 8px;
  border-radius: 6px;
}

.action-btn {
  opacity: 0;
  transform: translateX(-10px);
  transition: all 0.3s ease;
}

.agent-card:hover .action-btn {
  opacity: 1;
  transform: translateX(0);
}
</style>
