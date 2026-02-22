<template>
  <el-container class="edit-layout">
    <el-header class="edit-header glass-panel">
      <div class="header-content">
        <div class="left">
          <el-button link @click="goBack">
            <el-icon><ArrowLeft /></el-icon> 返回
          </el-button>
          <h2>{{ isEdit ? (isBuiltin ? '版本管理' : '编辑 Agent') : '新建 Agent' }}</h2>
          <!-- Version selector + status badge -->
          <template v-if="isEdit && versions.length">
            <el-select
              v-model="selectedVersion"
              size="small"
              class="version-select"
              @change="onVersionChange"
            >
              <el-option
                v-for="v in versions"
                :key="v.version"
                :label="`v${v.version}`"
                :value="v.version"
              >
                <span>v{{ v.version }}</span>
                <el-tag
                  :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'"
                  size="small"
                  effect="plain"
                  style="margin-left: 8px"
                >{{ v.status }}</el-tag>
              </el-option>
            </el-select>
            <el-tag
              v-if="currentVersionObj"
              :type="currentVersionObj.status === 'published' ? 'success' : currentVersionObj.status === 'draft' ? 'warning' : 'info'"
              effect="dark"
              size="small"
            >{{ currentVersionObj.status }}</el-tag>
          </template>
        </div>
        <div class="right">
          <el-button @click="showHistory = !showHistory" :icon="Clock">
            版本历史
          </el-button>
          <el-button @click="goBack">取消</el-button>
          <el-button type="primary" :loading="isSaving" :disabled="isBuiltin" @click="handleSave">
            保存草稿
          </el-button>
          <!-- PLACEHOLDER_PUBLISH_BTN -->
        </div>
      </div>
    </el-header>

    <el-main class="edit-main">
      <div class="content-wrapper">
        <!-- Main form -->
        <div class="form-area">
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
                <el-input v-model="form.name" placeholder="给你的 Agent 起个名字" :disabled="isBuiltin" />
              </el-form-item>

              <el-form-item label="描述" prop="description">
                <el-input
                  v-model="form.description"
                  type="textarea"
                  :rows="2"
                  placeholder="简要描述这个 Agent 的功能和用途"
                  :disabled="isBuiltin"
                />
              </el-form-item>

              <el-form-item label="模型" prop="model">
                <el-select v-model="form.model" class="full-width" placeholder="选择模型" :disabled="isBuiltin">
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
                    :min="0" :max="1" :step="0.1"
                    show-input
                    :disabled="isBuiltin"
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
                  :disabled="isBuiltin"
                />
                <div class="help-text">
                  定义 Agent 的角色、行为、限制和能力。
                </div>
              </el-form-item>
            </el-card>

            <!-- Publish action for draft -->
            <div v-if="isEdit && currentVersionObj?.status === 'draft'" class="publish-bar">
              <el-button type="success" :loading="isPublishing" @click="handlePublish">
                发布此版本 (v{{ currentVersionObj.version }})
              </el-button>
              <span class="help-text">发布后此版本将成为运行时使用的配置</span>
            </div>
          </el-form>
        </div>
        <!-- Version history side panel -->
        <transition name="slide">
          <div v-if="showHistory && isEdit" class="history-panel glass-panel-light">
            <div class="history-header">
              <h3>版本历史</h3>
              <el-button link @click="showHistory = false">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>
            <el-timeline class="version-timeline">
              <el-timeline-item
                v-for="v in versions"
                :key="v.version"
                :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'"
                :timestamp="formatTime(v.created_at)"
                placement="top"
              >
                <div class="timeline-card" :class="{ active: v.version === selectedVersion }">
                  <div class="timeline-title">
                    <span>v{{ v.version }}</span>
                    <el-tag
                      :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'"
                      size="small" effect="plain"
                    >{{ v.status }}</el-tag>
                  </div>
                  <p v-if="v.change_summary" class="timeline-summary">{{ v.change_summary }}</p>
                  <div class="timeline-actions">
                    <el-button size="small" link @click="onVersionChange(v.version)">查看</el-button>
                    <el-button
                      v-if="v.status !== 'draft'"
                      size="small" link type="warning"
                      @click="handleRollback(v.version)"
                    >回滚</el-button>
                    <el-button
                      v-if="agentData?.published_version && v.version !== agentData.published_version.version"
                      size="small" link type="primary"
                      @click="handleDiff(agentData.published_version.version, v.version)"
                    >Diff</el-button>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </transition>
      </div>
    </el-main>

    <!-- Diff dialog -->
    <el-dialog v-model="showDiff" title="版本对比" width="700px" class="diff-dialog">
      <div v-if="diffData">
        <div class="diff-header">
          <el-tag>v{{ diffData.v1 }}</el-tag>
          <span style="margin: 0 8px">→</span>
          <el-tag>v{{ diffData.v2 }}</el-tag>
        </div>
        <div v-if="Object.keys(diffData.diff).length === 0" class="diff-empty">
          两个版本配置完全相同
        </div>
        <div v-else class="diff-content">
          <div v-for="(changes, changeType) in diffData.diff" :key="changeType" class="diff-section">
            <h4>{{ diffLabel(changeType) }}</h4>
            <div v-for="(detail, path) in changes" :key="path" class="diff-item">
              <code class="diff-path">{{ path }}</code>
              <div v-if="detail.old_value !== undefined" class="diff-values">
                <span class="diff-old">- {{ detail.old_value }}</span>
                <span class="diff-new">+ {{ detail.new_value }}</span>
              </div>
              <div v-else class="diff-values">
                <span class="diff-new">{{ detail }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Clock, Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import apiClient from '@/api/client'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()

const isEdit = computed(() => route.params.id && route.params.id !== 'new')
const isBuiltin = computed(() => agentData.value?.type === 'builtin')
const isVersionRoute = computed(() => route.path.includes('/versions'))

function goBack() {
  if (isVersionRoute.value) {
    router.push('/agents')
  } else {
    router.push('/custom-agents')
  }
}
const isLoading = ref(false)
const isSaving = ref(false)
const isPublishing = ref(false)

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
  model: [{ required: true, message: '请选择模型', trigger: 'change' }],
  system_prompt: [{ required: true, message: '请输入系统提示词', trigger: 'blur' }]
})

// Version state
const agentData = ref<any>(null)
const versions = ref<any[]>([])
const selectedVersion = ref<number | null>(null)
const showHistory = ref(false)
const showDiff = ref(false)
const diffData = ref<any>(null)

const currentVersionObj = computed(() =>
  versions.value.find(v => v.version === selectedVersion.value) || null
)

onMounted(async () => {
  if (isEdit.value) {
    await loadAgent()
    await loadVersions()
    // Auto-open history panel for builtin agents
    if (isBuiltin.value) showHistory.value = true
  }
})

async function loadAgent() {
  isLoading.value = true
  try {
    const data = await apiClient.getAgent(route.params.id as string)
    agentData.value = data
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

async function loadVersions() {
  try {
    const id = route.params.id as string
    versions.value = await apiClient.listAgentVersions(id)
    // Default to draft if exists, otherwise published
    const draft = versions.value.find(v => v.status === 'draft')
    const published = versions.value.find(v => v.status === 'published')
    if (draft) {
      selectedVersion.value = draft.version
      applyVersionToForm(draft)
    } else if (published) {
      selectedVersion.value = published.version
    }
  } catch (error) {
    console.error('Failed to load versions', error)
  }
}

function applyVersionToForm(ver: any) {
  form.value = {
    name: agentData.value?.name || form.value.name,
    description: ver.config?.description || '',
    model: ver.config?.model || 'gpt-4o',
    temperature: ver.config?.temperature ?? 0.7,
    system_prompt: ver.config?.system_prompt || ''
  }
}

async function onVersionChange(version: number) {
  selectedVersion.value = version
  try {
    const id = route.params.id as string
    const ver = await apiClient.getAgentVersion(id, version)
    applyVersionToForm(ver)
  } catch (error) {
    ElMessage.error('加载版本失败')
  }
}

async function handleSave() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    isSaving.value = true
    try {
      const config = {
        description: form.value.description,
        model: form.value.model,
        temperature: form.value.temperature,
        system_prompt: form.value.system_prompt
      }
      if (isEdit.value) {
        const id = route.params.id as string
        // Update agent name + create/update draft via agents API
        await apiClient.updateAgent(id, { name: form.value.name, ...config })
        ElMessage.success('草稿已保存')
        await loadAgent()
        await loadVersions()
      } else {
        await apiClient.createAgent({
          name: form.value.name, ...config
        })
        ElMessage.success('创建成功')
        goBack()
      }
    } catch (error) {
      ElMessage.error('保存失败')
      console.error(error)
    } finally {
      isSaving.value = false
    }
  })
}

async function handlePublish() {
  if (!currentVersionObj.value) return
  try {
    await ElMessageBox.confirm(
      `确定要发布 v${currentVersionObj.value.version} 吗？发布后将替换当前运行版本。`,
      '发布确认',
      { confirmButtonText: '发布', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  isPublishing.value = true
  try {
    const id = route.params.id as string
    await apiClient.publishAgentVersion(id, currentVersionObj.value.version)
    ElMessage.success('发布成功')
    await loadAgent()
    await loadVersions()
  } catch (error) {
    ElMessage.error('发布失败')
    console.error(error)
  } finally {
    isPublishing.value = false
  }
}

async function handleRollback(version: number) {
  try {
    await ElMessageBox.confirm(
      `从 v${version} 创建新草稿？`,
      '回滚确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }

  try {
    const id = route.params.id as string
    const newDraft = await apiClient.rollbackAgentVersion(id, version)
    ElMessage.success(`已从 v${version} 创建草稿 v${newDraft.version}`)
    await loadAgent()
    await loadVersions()
  } catch (error) {
    ElMessage.error('回滚失败')
    console.error(error)
  }
}

async function handleDiff(v1: number, v2: number) {
  try {
    const id = route.params.id as string
    diffData.value = await apiClient.diffAgentVersions(id, v1, v2)
    showDiff.value = true
  } catch (error) {
    ElMessage.error('获取 Diff 失败')
    console.error(error)
  }
}

function formatTime(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

function diffLabel(key: string | number): string {
  const k = String(key)
  const map: Record<string, string> = {
    values_changed: '值变更',
    dictionary_item_added: '新增字段',
    dictionary_item_removed: '删除字段',
    type_changes: '类型变更',
    iterable_item_added: '列表新增',
    iterable_item_removed: '列表删除',
  }
  return map[k] || k
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
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.left { display: flex; align-items: center; gap: 12px; }
.left h2 { font-size: 18px; margin: 0; font-weight: 600; }
.right { display: flex; align-items: center; gap: 8px; }
.version-select { width: 100px; }
.edit-main { flex: 1; overflow-y: auto; padding: 24px; }
.content-wrapper {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  gap: 24px;
}
.form-area { flex: 1; min-width: 0; }
.edit-form { max-width: 800px; padding-bottom: 40px; }
.form-card {
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  padding: 8px;
}
.full-width { width: 100%; }
.slider-container { padding: 0 8px; }
.help-text {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.4;
}
.publish-bar {
  margin-top: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
}
/* Prompt editor */
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
:deep(.el-input__wrapper),
:deep(.el-textarea__inner) {
  box-shadow: none !important;
  border: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.05);
  transition: all 0.2s;
}
:deep(.el-input__wrapper:hover),
:deep(.el-textarea__inner:hover) { border-color: var(--text-tertiary); }
:deep(.el-input__wrapper.is-focus),
:deep(.el-textarea__inner:focus) {
  border-color: var(--accent-primary) !important;
  background: rgba(255, 255, 255, 0.08);
}

/* History panel */
.history-panel {
  width: 340px;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 20px;
  max-height: calc(100vh - 140px);
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.03);
}
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.history-header h3 { margin: 0; font-size: 16px; }
.version-timeline { padding-left: 4px; }
.timeline-card {
  padding: 8px 12px;
  border-radius: 8px;
  transition: background 0.2s;
  cursor: pointer;
}
.timeline-card:hover { background: rgba(255, 255, 255, 0.06); }
.timeline-card.active { background: rgba(99, 102, 241, 0.1); }
.timeline-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.timeline-summary {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 4px 0;
}
.timeline-actions { display: flex; gap: 4px; margin-top: 4px; }

/* Slide transition */
.slide-enter-active, .slide-leave-active { transition: all 0.3s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateX(20px); }

/* Diff dialog */
.diff-header {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}
.diff-empty {
  text-align: center;
  color: var(--text-tertiary);
  padding: 24px;
}
.diff-section { margin-bottom: 16px; }
.diff-section h4 { margin: 0 0 8px; font-size: 14px; }
.diff-item {
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.15);
  border-radius: 8px;
  margin-bottom: 8px;
}
.diff-path {
  font-size: 12px;
  color: var(--text-tertiary);
  display: block;
  margin-bottom: 4px;
}
.diff-values { font-size: 13px; }
.diff-old { color: #f56c6c; display: block; }
.diff-new { color: #67c23a; display: block; }
</style>