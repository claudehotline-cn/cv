<template>
  <el-container class="edit-layout">
    <el-header class="edit-header glass-panel">
      <div class="header-content">
        <div class="left">
          <el-button link @click="$router.push('/agents/prompts')">
            <el-icon><ArrowLeft /></el-icon> 返回
          </el-button>
          <h2>{{ template?.name || 'Prompt 编辑' }}</h2>
          <template v-if="versions.length">
            <el-select v-model="selectedVersion" size="small" class="version-select" @change="onVersionChange">
              <el-option v-for="v in versions" :key="v.version" :label="`v${v.version}`" :value="v.version">
                <span>v{{ v.version }}</span>
                <el-tag :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'" size="small" effect="plain" style="margin-left:8px">{{ v.status }}</el-tag>
              </el-option>
            </el-select>
            <el-tag v-if="currentVersionObj" :type="currentVersionObj.status === 'published' ? 'success' : currentVersionObj.status === 'draft' ? 'warning' : 'info'" effect="dark" size="small">{{ currentVersionObj.status }}</el-tag>
          </template>
        </div>
        <div class="right">
          <el-button @click="showHistory = !showHistory" :icon="Clock">版本历史</el-button>
          <el-button type="primary" :loading="isSaving" @click="handleSaveDraft">保存草稿</el-button>
        </div>
      </div>
    </el-header>

    <el-main class="edit-main">
      <div class="content-wrapper">
        <div class="form-area">
          <div v-if="isLoading" class="loading-state"><el-skeleton :rows="8" animated /></div>
          <template v-else>
            <!-- Meta info -->
            <el-card class="glass-panel-light form-card" shadow="never">
              <div class="meta-row">
                <span class="meta-label">Key:</span>
                <code>{{ template?.key }}</code>
              </div>
              <el-form label-position="top" class="meta-form">
                <el-form-item label="名称">
                  <el-input v-model="metaForm.name" @blur="saveMeta" />
                </el-form-item>
                <el-form-item label="描述">
                  <el-input v-model="metaForm.description" type="textarea" :rows="2" @blur="saveMeta" />
                </el-form-item>
                <el-form-item label="分类">
                  <el-input v-model="metaForm.category" @blur="saveMeta" />
                </el-form-item>
              </el-form>
            </el-card>

            <!-- Prompt editor -->
            <el-card class="glass-panel-light form-card" shadow="never">
              <div class="editor-header">
                <span class="editor-title">Prompt 内容</span>
                <el-button size="small" @click="handlePreview" :loading="isPreviewing">预览渲染</el-button>
              </div>
              <el-input
                v-model="promptContent"
                type="textarea"
                :rows="20"
                class="prompt-editor"
                placeholder="输入 Prompt 内容，支持 Jinja2 变量 {{ variable_name }}"
              />
            </el-card>

            <!-- Publish bar -->
            <div v-if="currentVersionObj?.status === 'draft'" class="publish-bar">
              <el-button type="success" :loading="isPublishing" @click="handlePublish">
                发布此版本 (v{{ currentVersionObj.version }})
              </el-button>
            </div>

            <!-- Variables panel -->
            <el-card class="glass-panel-light form-card" shadow="never">
              <div class="editor-header">
                <span class="editor-title">变量测试</span>
              </div>
              <div v-for="item in panelVars" :key="item.name" class="var-row">
                <div class="var-meta">
                  <span class="var-name" v-text="`{{ ${item.name} }}`"></span>
                  <span v-if="item.type" class="var-type">{{ item.type }}</span>
                  <span v-if="item.description" class="var-desc">{{ item.description }}</span>
                </div>
                <el-input v-model="testVars[item.name]" size="small" placeholder="测试值" />
              </div>
              <div v-if="!panelVars.length" class="empty-hint">未检测到变量</div>
              <div v-else-if="!schemaVars.length" class="empty-hint">未配置 variables_schema，当前为自动识别变量。</div>
            </el-card>

            <!-- Preview result -->
            <el-card v-if="previewResult" class="glass-panel-light form-card" shadow="never">
              <div class="editor-header">
                <span class="editor-title">渲染预览</span>
                <el-radio-group v-model="previewMode" size="small">
                  <el-radio-button value="rendered">Markdown</el-radio-button>
                  <el-radio-button value="source">源码</el-radio-button>
                </el-radio-group>
              </div>
              <div v-if="previewMode === 'rendered'" class="preview-markdown" v-html="renderedMarkdown"></div>
              <pre v-else class="preview-content">{{ previewResult }}</pre>
            </el-card>
          </template>
        </div>

        <!-- Version history sidebar -->
        <transition name="slide">
          <div v-if="showHistory" class="history-panel glass-panel-light">
            <div class="history-header">
              <h3>版本历史</h3>
              <el-button text @click="showHistory = false"><el-icon><Close /></el-icon></el-button>
            </div>
            <el-timeline class="version-timeline">
              <el-timeline-item
                v-for="v in versions" :key="v.version"
                :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'"
                :timestamp="v.created_at?.slice(0, 19).replace('T', ' ')"
                placement="top"
              >
                <div class="timeline-card" :class="{ active: v.version === selectedVersion }" @click="onVersionChange(v.version)">
                  <div class="timeline-title">
                    <span>v{{ v.version }}</span>
                    <el-tag :type="v.status === 'published' ? 'success' : v.status === 'draft' ? 'warning' : 'info'" size="small">{{ v.status }}</el-tag>
                  </div>
                  <div class="timeline-summary">{{ v.change_summary || '无备注' }}</div>
                  <div class="timeline-actions">
                    <el-button v-if="v.status !== 'draft'" size="small" text type="primary" @click.stop="handleRollback(v.version)">回滚</el-button>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </transition>
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Clock, Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import apiClient from '@/api/client'

const md = new MarkdownIt()

const route = useRoute()
const templateId = computed(() => route.params.id as string)

const template = ref<any>(null)
const versions = ref<any[]>([])
const selectedVersion = ref<number>(0)
const promptContent = ref('')
const testVars = ref<Record<string, string>>({})
const previewResult = ref('')
const previewMode = ref<'rendered' | 'source'>('rendered')

const isLoading = ref(false)
const isSaving = ref(false)
const isPublishing = ref(false)
const isPreviewing = ref(false)
const showHistory = ref(false)

const metaForm = ref({ name: '', description: '', category: '' })

type VarPanelItem = {
  name: string
  type?: string
  description?: string
  default?: string | number | boolean | null
}

const currentVersionObj = computed(() => versions.value.find(v => v.version === selectedVersion.value))

const renderedMarkdown = computed(() => md.render(previewResult.value || ''))

const schemaVars = computed<VarPanelItem[]>(() => {
  const schema = currentVersionObj.value?.variables_schema
  if (!schema) return []

  if (Array.isArray(schema)) {
    return schema
      .filter((x: any) => x && typeof x.name === 'string')
      .map((x: any) => ({
        name: x.name,
        type: x.type,
        description: x.description,
        default: x.default,
      }))
  }

  if (typeof schema === 'object') {
    return Object.entries(schema).map(([name, meta]: [string, any]) => ({
      name,
      type: meta?.type,
      description: meta?.description,
      default: meta?.default,
    }))
  }

  return []
})

const detectedVars = computed(() => {
  const text = promptContent.value
  const jinja = (text.match(/\{\{\s*(\w+)\s*\}\}/g) || []).map(m => m.replace(/[{}\s]/g, ''))
  const pyMatches: string[] = []
  const pyRe = /(?<!\{)\{(\w+)\}(?!\})/g
  let m
  while ((m = pyRe.exec(text)) !== null) {
    pyMatches.push(m[1])
  }
  return [...new Set([...jinja, ...pyMatches])]
})

const panelVars = computed<VarPanelItem[]>(() => {
  if (schemaVars.value.length) return schemaVars.value
  return detectedVars.value.map((name) => ({
    name,
    type: undefined,
    description: undefined,
    default: undefined,
  }))
})

onMounted(() => loadAll())

watch([panelVars, currentVersionObj], () => {
  const next: Record<string, string> = {}
  panelVars.value.forEach((item: any) => {
    const existing = testVars.value[item.name]
    if (existing !== undefined) {
      next[item.name] = existing
      return
    }
    if (item.default !== undefined && item.default !== null) {
      next[item.name] = String(item.default)
      return
    }
    next[item.name] = ''
  })
  testVars.value = next
}, { immediate: true })

async function loadAll() {
  isLoading.value = true
  try {
    template.value = await apiClient.getPrompt(templateId.value)
    metaForm.value = {
      name: template.value.name || '',
      description: template.value.description || '',
      category: template.value.category || '',
    }
    versions.value = await apiClient.listPromptVersions(templateId.value)
    // Select published or latest version
    const pub = versions.value.find(v => v.status === 'published')
    const draft = versions.value.find(v => v.status === 'draft')
    const target = draft || pub || versions.value[0]
    if (target) {
      selectedVersion.value = target.version
      promptContent.value = target.content || ''
    }
  } catch (e) {
    ElMessage.error('加载失败')
    console.error(e)
  } finally {
    isLoading.value = false
  }
}

function onVersionChange(ver: number) {
  selectedVersion.value = ver
  const v = versions.value.find(x => x.version === ver)
  if (v) promptContent.value = v.content || ''
  previewResult.value = ''
}

async function saveMeta() {
  try {
    await apiClient.updatePrompt(templateId.value, metaForm.value)
  } catch { /* silent */ }
}

async function handleSaveDraft() {
  isSaving.value = true
  try {
    if (currentVersionObj.value?.status === 'draft') {
      await apiClient.updatePromptDraft(templateId.value, selectedVersion.value, {
        content: promptContent.value,
        change_summary: 'Manual edit',
      })
      ElMessage.success('草稿已保存')
    } else {
      const res = await apiClient.createPromptDraft(templateId.value, {
        content: promptContent.value,
        base_version: selectedVersion.value,
        change_summary: 'New draft',
      })
      ElMessage.success(`已创建草稿 v${res.version}`)
    }
    versions.value = await apiClient.listPromptVersions(templateId.value)
    const draft = versions.value.find(v => v.status === 'draft')
    if (draft) selectedVersion.value = draft.version
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    isSaving.value = false
  }
}

async function handlePublish() {
  try {
    await ElMessageBox.confirm('确定要发布此版本吗？当前已发布版本将被归档。', '发布确认', { type: 'warning' })
  } catch { return }
  isPublishing.value = true
  try {
    await apiClient.publishPromptVersion(templateId.value, selectedVersion.value)
    ElMessage.success('发布成功')
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  } finally {
    isPublishing.value = false
  }
}

async function handleRollback(ver: number) {
  try {
    const res = await apiClient.rollbackPromptVersion(templateId.value, ver)
    ElMessage.success(`已从 v${ver} 创建草稿 v${res.version}`)
    versions.value = await apiClient.listPromptVersions(templateId.value)
    selectedVersion.value = res.version
    promptContent.value = res.content || ''
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '回滚失败')
  }
}

async function handlePreview() {
  isPreviewing.value = true
  try {
    const res = await apiClient.previewPrompt(templateId.value, {
      content: promptContent.value,
      variables: testVars.value,
    })
    previewResult.value = res.rendered
  } catch (e: any) {
    ElMessage.error('预览失败')
  } finally {
    isPreviewing.value = false
  }
}
</script>

<style scoped>
.edit-layout { height: 100vh; display: flex; flex-direction: column; background: var(--bg-primary); }
.edit-header { height: auto !important; padding: 16px 24px; border-bottom: 1px solid var(--border-color); }
.header-content { display: flex; justify-content: space-between; align-items: center; max-width: 1400px; margin: 0 auto; width: 100%; }
.left, .right { display: flex; align-items: center; gap: 12px; }
.left h2 { margin: 0; font-size: 18px; }
.version-select { width: 100px; }
.edit-main { flex: 1; overflow-y: auto; padding: 24px; }
.content-wrapper { display: flex; gap: 24px; max-width: 1400px; margin: 0 auto; }
.form-area { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.form-card { border-radius: 12px; }
.meta-row { margin-bottom: 12px; }
.meta-row code { font-size: 14px; color: var(--el-color-primary); background: rgba(99,102,241,0.1); padding: 2px 8px; border-radius: 4px; }
.meta-label { font-size: 13px; color: var(--text-secondary); margin-right: 8px; }
.meta-form :deep(.el-form-item) { margin-bottom: 12px; }
.editor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.editor-title { font-weight: 600; font-size: 15px; }
.prompt-editor :deep(textarea) { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 13px; line-height: 1.6; }
.publish-bar { display: flex; justify-content: flex-end; }
.var-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.var-name { font-family: monospace; font-size: 13px; color: var(--el-color-warning); min-width: 160px; }
.empty-hint { color: var(--text-tertiary); font-size: 13px; }
.preview-content { white-space: pre-wrap; font-family: monospace; font-size: 13px; line-height: 1.6; max-height: 400px; overflow-y: auto; background: rgba(0,0,0,0.1); padding: 16px; border-radius: 8px; margin: 0; }
.preview-markdown { max-height: 500px; overflow-y: auto; padding: 16px; background: rgba(0,0,0,0.05); border-radius: 8px; font-size: 14px; line-height: 1.7; }
.preview-markdown :deep(h1) { font-size: 20px; margin: 16px 0 8px; }
.preview-markdown :deep(h2) { font-size: 17px; margin: 14px 0 6px; }
.preview-markdown :deep(h3) { font-size: 15px; margin: 12px 0 4px; }
.preview-markdown :deep(table) { border-collapse: collapse; width: 100%; margin: 12px 0; }
.preview-markdown :deep(th), .preview-markdown :deep(td) { border: 1px solid var(--border-color); padding: 6px 10px; font-size: 13px; }
.preview-markdown :deep(code) { background: rgba(99,102,241,0.1); padding: 2px 6px; border-radius: 4px; font-size: 13px; }
.preview-markdown :deep(pre) { background: rgba(0,0,0,0.15); padding: 12px; border-radius: 8px; overflow-x: auto; }
.preview-markdown :deep(ul), .preview-markdown :deep(ol) { padding-left: 20px; }
.preview-markdown :deep(blockquote) { border-left: 3px solid var(--el-color-primary); padding-left: 12px; color: var(--text-secondary); }
.history-panel { width: 320px; flex-shrink: 0; padding: 20px; border-radius: 12px; max-height: calc(100vh - 120px); overflow-y: auto; }
.history-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.history-header h3 { margin: 0; font-size: 16px; }
.timeline-card { padding: 8px 12px; border-radius: 8px; cursor: pointer; transition: background 0.2s; }
.timeline-card:hover { background: rgba(255,255,255,0.06); }
.timeline-card.active { background: rgba(99,102,241,0.1); }
.timeline-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.timeline-summary { font-size: 12px; color: var(--text-tertiary); margin: 4px 0; }
.timeline-actions { display: flex; gap: 4px; margin-top: 4px; }
.slide-enter-active, .slide-leave-active { transition: all 0.3s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateX(20px); }
</style>