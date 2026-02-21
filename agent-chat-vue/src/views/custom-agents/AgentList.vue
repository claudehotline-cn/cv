<template>
  <el-container class="settings-layout">
    <el-header class="glass-panel header">
      <div class="header-content">
        <h2>自定义 Agent</h2>
        <el-button type="primary" :icon="Plus" round @click="$router.push('/agents/create')">
          新建 Agent
        </el-button>
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
        >
          <div class="card-icon" :style="{ background: getGradient(agent.name) }">
            <el-icon><Cpu /></el-icon>
          </div>
          
          <div class="card-content">
            <div class="card-header">
              <h3>{{ agent.name }}</h3>
              <el-tag :type="agent.type === 'builtin' ? 'success' : 'primary'" size="small" effect="light">
                {{ agent.type === 'builtin' ? '官方' : '自定义' }}
              </el-tag>
            </div>
            
            <p class="description">{{ agent.config?.description || '暂无描述' }}</p>
            
            <div class="agent-meta">
              <span class="model-tag">
                <el-icon><Connection /></el-icon>
                {{ agent.config?.model || 'gpt-4o' }}
              </span>
            </div>

            <div class="card-actions">
              <el-button 
                size="small" 
                round
                @click="$router.push(`/custom-agents/${agent.id}`)"
                :disabled="agent.type === 'builtin'"
              >
                编辑
              </el-button>
              <el-popconfirm 
                v-if="agent.type !== 'builtin'"
                title="确定要删除这个 Agent 吗?"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="handleDelete(agent.id)"
              >
                <template #reference>
                  <el-button size="small" type="danger" :icon="Delete" circle />
                </template>
              </el-popconfirm>
            </div>
          </div>
        </div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, Delete, Cpu, Connection } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'

const agents = ref<any[]>([])
const isLoading = ref(false)

onMounted(async () => {
  await loadAgents()
})

async function loadAgents() {
  isLoading.value = true
  try {
    agents.value = await apiClient.listAgents()
  } catch (error) {
    ElMessage.error('加载 Agent 列表失败')
    console.error(error)
  } finally {
    isLoading.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await apiClient.deleteAgent(id)
    ElMessage.success('Agent 已删除')
    await loadAgents()
  } catch (error) {
    ElMessage.error('删除失败')
    console.error(error)
  }
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
.settings-layout {
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
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header h2 {
  font-size: 32px;
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
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
  min-width: 0;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-right: 8px;
}

.description {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 16px;
  height: 42px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}

.agent-meta {
  margin-bottom: 16px;
}

.model-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
  background: rgba(255, 255, 255, 0.05);
  padding: 4px 8px;
  border-radius: 6px;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}
</style>
