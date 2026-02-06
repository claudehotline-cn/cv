<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'
import { useAgentBuilderStore } from '@/stores/agentBuilder'
import AgentBuilderSteps from '@/components/agent-builder/AgentBuilderSteps.vue'
import AgentBuilderHeader from '@/components/agent-builder/AgentBuilderHeader.vue'

const router = useRouter()
const store = useAgentBuilderStore()
const draft = computed(() => store.draft)

const testMessage = ref('')
const publishing = ref(false)

function goBack() {
  router.push('/agents/create/knowledge')
}

function editIdentity() {
  router.push('/agents/create/identity')
}

function editCapabilities() {
  router.push('/agents/create/capabilities')
}

function editKnowledge() {
  router.push('/agents/create/knowledge')
}

function saveDraft() {
  ElMessage.success('Draft saved (mock)')
}

async function publishAgent() {
  publishing.value = true
  try {
    const config = {
      name: draft.value.name,
      description: draft.value.description,
      system_prompt: draft.value.system_prompt,
      model: 'gpt-4o',
      temperature: 0.7,
      tools: draft.value.tools,
      openapi_schema: {
        name: draft.value.openapi_schema_name,
        text: draft.value.openapi_schema_text,
      },
      knowledge: draft.value.knowledge,
    }
    await apiClient.createAgent(config)
    ElMessage.success('Agent published')
    router.push('/agents')
  } catch (e) {
    ElMessage.error('Publish failed')
  } finally {
    publishing.value = false
  }
}

function sendTest() {
  if (!testMessage.value.trim()) return
  ElMessage.info('Playground is mock UI for now')
  testMessage.value = ''
}

const enabledTools = computed(() => {
  const t = draft.value.tools
  const out: { key: string; title: string; desc: string; icon: string }[] = []
  if (t.web_search) {
    out.push({ key: 'web', title: 'Web Browser', desc: 'Access real-time information from the internet', icon: 'globe' })
  }
  if (t.code_interpreter) {
    out.push({ key: 'code', title: 'Code Interpreter', desc: 'Execute Python code for data analysis', icon: 'terminal' })
  }
  if (t.image_generation) {
    out.push({ key: 'img', title: 'Image Generation', desc: 'Create images from text prompts', icon: 'image' })
  }
  return out
})

const knowledgeCards = computed(() => {
  return (draft.value.knowledge || []).slice(0, 6)
})
</script>

<template>
  <div class="ab-root h-full flex overflow-hidden selection:bg-primary/30">
    <el-container class="w-full h-full min-h-0 bg-background-light dark:bg-background-dark">
      <el-header height="88px" class="!p-0">
        <AgentBuilderHeader
          title="Review & Publish"
          subtitle="Review your agent's configuration and test it before publishing."
        >
          <template #actions>
            <el-button text class="!font-black" @click="saveDraft">Save Draft</el-button>
          </template>
        </AgentBuilderHeader>
      </el-header>

        <el-main class="!p-0 flex-1 min-h-0 flex flex-col overflow-hidden">
          <div class="ab-review-body">
            <div class="ab-steps-panel mb-6">
              <AgentBuilderSteps />
            </div>

            <div class="ab-review-grid grid grid-cols-1 lg:grid-cols-12 gap-6">
              <!-- Left Column: Summary -->
              <el-scrollbar class="lg:col-span-7 pr-2 min-h-0 h-full">
                <div class="flex flex-col gap-6">
                  <el-card shadow="never" class="ab-card">
                    <div class="flex items-center justify-between mb-4">
                      <h3 class="text-lg font-black text-text-main dark:text-white flex items-center gap-2">
                        <span class="material-symbols-outlined text-primary">person</span>
                        Identity Summary
                      </h3>
                      <el-button text class="!p-0 text-xs font-black text-primary" @click="editIdentity">Edit</el-button>
                    </div>

                    <div class="grid grid-cols-[30%_1fr] gap-y-4 text-sm">
                      <div class="text-text-secondary py-2 border-b border-slate-100 dark:border-slate-800">Agent Name</div>
                      <div class="font-bold text-text-main dark:text-white py-2 border-b border-slate-100 dark:border-slate-800">
                        {{ draft.name || '—' }}
                      </div>

                      <div class="text-text-secondary py-2 border-b border-slate-100 dark:border-slate-800">Description</div>
                      <div class="font-bold text-text-main dark:text-white py-2 border-b border-slate-100 dark:border-slate-800">
                        {{ draft.description || '—' }}
                      </div>

                      <div class="text-text-secondary py-2">Base Model</div>
                      <div class="font-bold text-text-main dark:text-white py-2 flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-green-500"></span>
                        GPT-4 Turbo
                      </div>
                    </div>
                  </el-card>

                  <el-card shadow="never" class="ab-card">
                    <div class="flex items-center justify-between mb-4">
                      <h3 class="text-lg font-black text-text-main dark:text-white flex items-center gap-2">
                        <span class="material-symbols-outlined text-primary">build</span>
                        Enabled Tools
                      </h3>
                      <el-button text class="!p-0 text-xs font-black text-primary" @click="editCapabilities">Edit</el-button>
                    </div>

                    <div class="flex flex-col gap-3">
                      <div
                        v-for="tool in enabledTools"
                        :key="tool.key"
                        class="flex items-center gap-4 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700"
                      >
                        <div class="bg-white dark:bg-slate-700 p-2 rounded-md shadow-sm">
                          <span class="material-symbols-outlined text-slate-600 dark:text-slate-200">{{ tool.icon }}</span>
                        </div>
                        <div>
                          <p class="text-sm font-black text-text-main dark:text-white">{{ tool.title }}</p>
                          <p class="text-xs text-text-secondary dark:text-slate-400">{{ tool.desc }}</p>
                        </div>
                        <div class="ml-auto">
                          <el-tag type="success" effect="light" round class="ab-pill">Active</el-tag>
                        </div>
                      </div>

                      <div v-if="!enabledTools.length" class="text-sm text-text-secondary">No tools enabled.</div>
                    </div>
                  </el-card>

                  <el-card shadow="never" class="ab-card mb-8">
                    <div class="flex items-center justify-between mb-4">
                      <h3 class="text-lg font-black text-text-main dark:text-white flex items-center gap-2">
                        <span class="material-symbols-outlined text-primary">menu_book</span>
                        Knowledge Base
                      </h3>
                      <el-button text class="!p-0 text-xs font-black text-primary" @click="editKnowledge">Edit</el-button>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div
                        v-for="k in knowledgeCards"
                        :key="k.id"
                        class="flex items-center gap-3 p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/30"
                      >
                        <span
                          class="material-symbols-outlined"
                          :class="k.type === 'url' ? 'text-purple-500' : (String((k as any).name || '').endsWith('.pdf') ? 'text-red-500' : 'text-blue-500')"
                        >
                          {{ k.type === 'url' ? 'language' : (String((k as any).name || '').endsWith('.pdf') ? 'picture_as_pdf' : 'description') }}
                        </span>
                        <div class="flex-1 min-w-0">
                          <p class="text-sm font-bold text-text-main dark:text-white truncate">
                            {{ k.type === 'url' ? (k as any).url : (k as any).name }}
                          </p>
                          <p class="text-xs text-text-secondary dark:text-slate-400">
                            {{ k.type === 'url' ? (k as any).metaLabel : (k as any).sizeLabel }}
                          </p>
                        </div>
                      </div>
                    </div>
                  </el-card>
                </div>
              </el-scrollbar>

              <!-- Right Column: Test Playground -->
              <el-card shadow="never" class="lg:col-span-5 ab-playground !p-0 overflow-hidden relative min-h-0 h-full">
                <div class="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
                  <div class="flex items-center gap-2">
                    <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                    <h3 class="font-black text-sm text-slate-700 dark:text-slate-200">Test Playground</h3>
                  </div>
                  <el-button text class="ab-icon-btn" @click="ElMessage.info('Refresh: coming soon')">
                    <span class="material-symbols-outlined text-[20px]">refresh</span>
                  </el-button>
                </div>

                <el-scrollbar class="ab-chat flex-1 min-h-0">
                  <div class="p-4 bg-slate-50 dark:bg-[#122329] flex flex-col gap-4">
                    <div class="flex justify-center my-2">
                      <span class="text-xs text-slate-400 bg-slate-200/50 dark:bg-slate-800/50 px-2 py-1 rounded">Session Started</span>
                    </div>

                    <div class="flex gap-3">
                      <div class="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-blue-500 flex items-center justify-center text-white shrink-0 shadow-sm">
                        <span class="material-symbols-outlined text-[16px]">smart_toy</span>
                      </div>
                      <div class="flex flex-col gap-1 max-w-[85%]">
                        <span class="text-xs font-bold text-slate-500 dark:text-slate-400 ml-1">{{ draft.name || 'Support Bot' }}</span>
                        <div class="bg-white dark:bg-slate-700 p-3 rounded-2xl rounded-tl-none shadow-sm border border-slate-100 dark:border-slate-600 text-sm text-slate-800 dark:text-slate-100">
                          Hello! I'm your {{ draft.name || 'Customer Support Bot' }}. How can I assist you with your account today?
                        </div>
                      </div>
                    </div>

                    <div class="flex gap-3 flex-row-reverse">
                      <div class="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-600 flex items-center justify-center text-slate-600 dark:text-slate-200 shrink-0">
                        <span class="material-symbols-outlined text-[16px]">person</span>
                      </div>
                      <div class="flex flex-col gap-1 max-w-[85%] items-end">
                        <div class="bg-primary text-white p-3 rounded-2xl rounded-tr-none shadow-sm text-sm">
                          I'm having trouble logging in.
                        </div>
                      </div>
                    </div>

                    <div class="flex gap-3">
                      <div class="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-blue-500 flex items-center justify-center text-white shrink-0 shadow-sm">
                        <span class="material-symbols-outlined text-[16px]">smart_toy</span>
                      </div>
                      <div class="flex flex-col gap-1 max-w-[85%]">
                        <span class="text-xs font-bold text-slate-500 dark:text-slate-400 ml-1">{{ draft.name || 'Support Bot' }}</span>
                        <div class="bg-white dark:bg-slate-700 p-3 rounded-2xl rounded-tl-none shadow-sm border border-slate-100 dark:border-slate-600 text-sm text-slate-800 dark:text-slate-100">
                          <p>I can help with that. Are you seeing any specific error message when you try to log in?</p>
                          <div class="mt-2 flex items-center gap-2 p-2 bg-slate-50 dark:bg-slate-800 rounded border border-slate-100 dark:border-slate-600">
                            <span class="material-symbols-outlined text-[14px] text-slate-400">search</span>
                            <span class="text-xs text-slate-500 dark:text-slate-400 italic">Searching knowledge base for &quot;login issues&quot;...</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </el-scrollbar>

                <div class="p-3 bg-surface-light dark:bg-surface-dark border-t border-slate-200 dark:border-slate-800">
                  <div class="relative">
                    <el-input
                      v-model="testMessage"
                      type="textarea"
                      :rows="1"
                      autosize
                      placeholder="Type a message to test..."
                      class="ab-chat-input"
                      @keydown.enter.exact.prevent="sendTest"
                    />
                    <el-button
                      type="primary"
                      class="ab-send-btn"
                      :disabled="!testMessage.trim()"
                      @click="sendTest"
                    >
                      <span class="material-symbols-outlined text-[20px]">send</span>
                    </el-button>
                  </div>

                  <div class="flex justify-between items-center mt-2 px-1">
                    <p class="text-[10px] text-slate-400">AI responses may be inaccurate.</p>
                    <el-button text class="!p-0 text-[10px] font-bold text-slate-500" @click="ElMessage.info('Model config: coming soon')">
                      <span class="material-symbols-outlined text-[12px] mr-1">settings</span>
                      Model Config
                    </el-button>
                  </div>
                </div>
              </el-card>
            </div>
          </div>

          <!-- Footer Action Bar (pinned) -->
          <div class="ab-footer shrink-0">
            <el-button text class="!px-6 !py-2.5 !rounded-xl !font-black" @click="goBack">
              <span class="material-symbols-outlined mr-1">arrow_back</span>
              Back
            </el-button>
            <div class="flex items-center gap-4">
              <div class="text-sm text-text-secondary dark:text-slate-400 hidden sm:block">
                <span class="material-symbols-outlined align-middle text-[18px] mr-1">check</span>
                All checks passed
              </div>
              <el-button type="primary" class="!px-8 !py-3 !rounded-xl !font-black" :loading="publishing" @click="publishAgent">
                <span class="material-symbols-outlined mr-1">rocket_launch</span>
                Publish Agent
              </el-button>
            </div>
          </div>
        </el-main>
      </el-container>
  </div>
</template>

<style scoped>
.ab-card :deep(.el-card__body) {
  padding: 24px;
}

.ab-playground :deep(.el-card__body) {
  padding: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.ab-review-body {
  flex: 1;
  min-height: 0;
  padding: 20px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ab-review-grid {
  flex: 1;
  min-height: 0;
}

.ab-playground {
  min-height: 0;
}

.ab-chat {
  flex: 1;
  min-height: 0;
}

.ab-footer {
  padding: 14px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(226, 232, 240, 1);
}

.dark .ab-footer {
  background: rgba(22, 42, 48, 0.92);
  border-top-color: rgba(42, 63, 69, 1);
}

.ab-chat-input :deep(.el-textarea__inner) {
  padding-right: 56px !important;
  border-radius: 14px !important;
}

.ab-send-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  height: 34px;
  width: 38px;
  padding: 0;
  border-radius: 10px;
}

.ab-pill {
  border: 1px solid rgba(34, 197, 94, 0.22) !important;
  font-weight: 700;
}

@media (max-width: 1024px) {
  .ab-review-body {
    overflow-y: auto;
  }

  .ab-review-grid {
    height: auto;
  }

  .ab-playground {
    height: auto;
    max-height: 70vh;
  }
}
</style>
