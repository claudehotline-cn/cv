<template>
  <el-container class="edit-layout">
    <el-header class="edit-header glass-panel">
      <div class="header-content">
        <div class="left">
          <el-button link @click="$router.push('/custom-agents')">
            <el-icon><ArrowLeft /></el-icon> 返回
          </el-button>
          <h2>{{ isEdit ? '编辑 Agent' : '新建 Agent' }}</h2>
        </div>
        <div class="right">
          <el-button @click="$router.push('/custom-agents')">取消</el-button>
          <el-button type="primary" :loading="isSaving" @click="handleSave">
            保存
          </el-button>
        </div>
      </div>
    </el-header>

    <el-main class="edit-main">
      <div v-if="isLoading" class="loading-state">
        <el-skeleton :rows="5" animated />
      </div>

      <el-form
        v-else
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="edit-form"
      >
        <el-card class="glass-panel-light form-card" shadow="never">
          <el-form-item label="名称" prop="name">
            <el-input v-model="form.name" placeholder="给你的 Agent 起个名字" />
          </el-form-item>
          
          <el-form-item label="描述" prop="description">
            <el-input 
              v-model="form.description" 
              type="textarea" 
              :rows="2"
              placeholder="简要描述这个 Agent 的功能和用途" 
            />
          </el-form-item>

          <el-form-item label="模型" prop="model">
            <el-select v-model="form.model" class="full-width" placeholder="选择模型">
              <el-option label="GPT-4o" value="gpt-4o" />
              <el-option label="GPT-4o Mini" value="gpt-4o-mini" />
              <el-option label="Qwen3 (72B)" value="qwen3:72b" />
              <el-option label="Qwen3 (30B)" value="qwen3:30b" />
              <el-option label="Qwen 2.5 (32B)" value="qwen2.5:32b" />
            </el-select>
          </el-form-item>

          <el-form-item label="温度 (Temperature)" prop="temperature">
            <div class="slider-container">
              <el-slider 
                v-model="form.temperature" 
                :min="0" 
                :max="1" 
                :step="0.1" 
                show-input
              />
            </div>
            <div class="help-text">
              数值越高回复越随机及有创造力，数值越低回复越严谨确切。
            </div>
          </el-form-item>

          <el-form-item label="系统提示词 (System Prompt)" prop="system_prompt">
            <el-input 
              v-model="form.system_prompt" 
              type="textarea" 
              :rows="12"
              placeholder="你是一个专业的助手..." 
              class="prompt-editor"
            />
            <div class="help-text">
              定义 Agent 的角色、行为、限制和能力。
            </div>
          </el-form-item>
        </el-card>
      </el-form>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import apiClient from '@/api/client'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()

const isEdit = computed(() => route.params.id && route.params.id !== 'new')
const isLoading = ref(false)
const isSaving = ref(false)

const form = ref({
  name: '',
  description: '',
  model: 'gpt-4o',
  temperature: 0.7,
  system_prompt: ''
})

const rules = ref<FormRules>({
  name: [
    { required: true, message: '请输入 Agent 名称', trigger: 'blur' },
    { min: 2, max: 50, message: '长度在 2 到 50 个字符', trigger: 'blur' }
  ],
  model: [
    { required: true, message: '请选择模型', trigger: 'change' }
  ],
  system_prompt: [
    { required: true, message: '请输入系统提示词', trigger: 'blur' }
  ]
})

onMounted(async () => {
  if (isEdit.value) {
    await loadAgent()
  }
})

async function loadAgent() {
  isLoading.value = true
  try {
    const data = await apiClient.getAgent(route.params.id as string)
    form.value = {
      name: data.name,
      description: data.config?.description || '',
      model: data.config?.model || 'gpt-4o',
      temperature: data.config?.temperature ?? 0.7,
      system_prompt: data.config?.system_prompt || ''
    }
  } catch (error) {
    ElMessage.error('加载 Agent 失败')
    console.error(error)
  } finally {
    isLoading.value = false
  }
}

async function handleSave() {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      isSaving.value = true
      try {
        const config = {
          name: form.value.name,
          description: form.value.description,
          model: form.value.model,
          temperature: form.value.temperature,
          system_prompt: form.value.system_prompt
        }

        if (isEdit.value) {
          await apiClient.updateAgent(route.params.id as string, config)
          ElMessage.success('更新成功')
        } else {
          await apiClient.createAgent(config)
          ElMessage.success('创建成功')
        }
        router.push('/custom-agents')
      } catch (error) {
        ElMessage.error('保存失败')
        console.error(error)
      } finally {
        isSaving.value = false
      }
    }
  })
}
</script>

<style scoped>
.edit-layout {
  height: 100vh;
  background: var(--bg-primary);
  display: flex;
  flex-direction: column;
}

.edit-header {
  height: auto !important;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color);
  background: var(--glass-bg);
}

.header-content {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.left h2 {
  font-size: 18px;
  margin: 0;
  font-weight: 600;
}

.edit-main {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.edit-form {
  max-width: 800px;
  margin: 0 auto;
  padding-bottom: 40px;
}

.form-card {
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  padding: 8px; /* Extra padding inside card */
}

.full-width {
  width: 100%;
}

.slider-container {
  padding: 0 8px;
}

.help-text {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.4;
}

.prompt-editor :deep(.el-textarea__inner) {
  font-family: 'JetBrains Mono', 'Menlo', 'Monaco', monospace;
  font-size: 14px;
  line-height: 1.6;
  background: rgba(0, 0, 0, 0.2);
  border-color: var(--border-color);
}

.prompt-editor :deep(.el-textarea__inner:focus) {
  border-color: var(--accent-primary);
  background: rgba(0, 0, 0, 0.3);
}

/* Custom Input Styling */
:deep(.el-input__wrapper),
:deep(.el-textarea__inner) {
  box-shadow: none !important;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.05);
  transition: all 0.2s;
}

:deep(.el-input__wrapper:hover),
:deep(.el-textarea__inner:hover) {
  border-color: var(--text-tertiary);
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-textarea__inner:focus) {
  border-color: var(--accent-primary) !important;
  background: rgba(255, 255, 255, 0.08);
}
</style>
