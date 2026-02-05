<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentBuilderStore } from '@/stores/agentBuilder'

const router = useRouter()
const store = useAgentBuilderStore()
const draft = computed(() => store.draft)

function goBack() {
  router.push('/agents/create/capabilities')
}

function goNext() {
  router.push('/agents/create/review')
}

async function onFilesPicked(files: File[]) {
  const list = (files || []).filter(Boolean)
  if (!list.length) return

  for (const f of list) {
    draft.value.knowledge.unshift({
      id: `file_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      type: 'file',
      name: f.name,
      sizeLabel: `${Math.max(1, Math.round((f.size / 1024 / 1024) * 10) / 10)} MB`,
      status: 'processing',
      progress: 20,
    } as any)
  }

  ElMessage.success('Files added (mock)')
}

async function onUploadChanged(uploadFile: any) {
  const raw = uploadFile?.raw as File | undefined
  if (!raw) return
  await onFilesPicked([raw])
}

function addSource() {
  const before = draft.value.knowledge.length
  store.addWebsiteSource()
  if (draft.value.knowledge.length === before) {
    ElMessage.warning('Enter a URL first')
  } else {
    ElMessage.success('Source added')
  }
}

function statusPill(item: any) {
  if (item.type === 'url') return 'Synced'
  if (item.status === 'ready') return 'Ready'
  return 'Processing'
}
</script>

<template>
  <el-container class="ab-root bg-background-light dark:bg-background-dark font-display text-text-main antialiased selection:bg-primary/30 h-screen overflow-hidden">
    <!-- Sidebar Navigation -->
    <el-aside
      width="288px"
      class="flex w-72 flex-col justify-between border-r border-slate-200 bg-surface-light dark:bg-surface-dark dark:border-slate-800 p-6 shadow-sm z-10 h-full"
    >
        <div class="flex flex-col gap-8">
          <div class="flex flex-col gap-1">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-primary text-3xl">smart_toy</span>
              <h1 class="text-xl font-black tracking-tight text-text-main dark:text-white">Agent Wizard</h1>
            </div>
            <p class="text-sm font-bold text-text-secondary dark:text-slate-400 pl-9">Create new agent</p>
          </div>

          <nav class="flex flex-col gap-2">
            <el-button text class="!h-auto !p-0 !w-full" @click="router.push('/agents/create/identity')">
              <div class="group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/50 text-left w-full">
                <div class="flex items-center justify-center text-green-500">
                  <span class="material-symbols-outlined">check_circle</span>
                </div>
                <div class="flex flex-col">
                  <span class="text-sm font-black text-text-main dark:text-slate-200">Identity</span>
                  <span class="text-xs text-text-secondary dark:text-slate-500">Completed</span>
                </div>
              </div>
            </el-button>

            <el-button text class="!h-auto !p-0 !w-full" @click="router.push('/agents/create/capabilities')">
              <div class="group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800/50 text-left w-full">
                <div class="flex items-center justify-center text-green-500">
                  <span class="material-symbols-outlined">check_circle</span>
                </div>
                <div class="flex flex-col">
                  <span class="text-sm font-black text-text-main dark:text-slate-200">Tools</span>
                  <span class="text-xs text-text-secondary dark:text-slate-500">Completed</span>
                </div>
              </div>
            </el-button>

            <div class="flex cursor-default items-center gap-3 rounded-lg bg-primary/10 px-3 py-2.5 ring-1 ring-primary/20 dark:bg-primary/5">
              <div class="flex items-center justify-center text-primary">
                <span class="material-symbols-outlined">menu_book</span>
              </div>
              <div class="flex flex-col">
                <span class="text-sm font-black text-text-main dark:text-white">Knowledge</span>
                <span class="text-xs font-bold text-primary">In Progress</span>
              </div>
            </div>

            <el-button text class="!h-auto !p-0 !w-full" @click="router.push('/agents/create/review')">
              <div class="group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 opacity-50 hover:opacity-100 transition-all text-left w-full">
                <div class="flex items-center justify-center text-text-secondary">
                  <span class="material-symbols-outlined">rocket_launch</span>
                </div>
                <div class="flex flex-col">
                  <span class="text-sm font-bold text-text-main dark:text-slate-200">Deployment</span>
                  <span class="text-xs text-text-secondary dark:text-slate-500">Pending</span>
                </div>
              </div>
            </el-button>
          </nav>
        </div>

        <div class="flex items-center gap-3 rounded-xl bg-slate-50 p-4 dark:bg-slate-800/50">
          <span class="material-symbols-outlined text-text-secondary">help</span>
          <div class="flex flex-col">
            <span class="text-xs font-black text-text-main dark:text-white">Need help?</span>
            <el-link type="primary" :underline="false" class="!text-xs !font-bold" @click="ElMessage.info('Docs: coming soon')">
              Read Documentation
            </el-link>
          </div>
        </div>
    </el-aside>

    <!-- Main Content Area -->
    <el-main class="!p-0 flex-1 min-h-0 overflow-y-auto bg-background-light dark:bg-background-dark">
      <div class="mx-auto w-full max-w-5xl px-8 py-10 pb-16">
          <div class="mb-10 flex flex-col gap-2">
            <h2 class="text-4xl font-black tracking-tight text-text-main dark:text-white">Knowledge Base</h2>
            <p class="max-w-2xl text-lg text-text-secondary dark:text-slate-400">
              Upload documents or add links to train your agent on specific topics. The more context you provide, the smarter your
              agent becomes.
            </p>
          </div>

          <div class="flex flex-col gap-8">
            <!-- Drag & Drop Zone -->
            <el-upload
              drag
              action=""
              multiple
              :show-file-list="false"
              :auto-upload="false"
              :on-change="onUploadChanged"
              class="ab-upload-zone"
            >
              <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
                <span class="material-symbols-outlined text-3xl">cloud_upload</span>
              </div>
              <h3 class="mb-2 text-xl font-black text-text-main dark:text-white">Upload Knowledge Files</h3>
              <p class="mb-6 max-w-sm text-sm text-text-secondary dark:text-slate-400">
                Drag and drop PDF, TXT, MD, or CSV files here to upload instantly.
              </p>
              <el-button type="primary" class="!px-6 !py-2.5 !rounded-lg !text-sm !font-black">Browse Files</el-button>
            </el-upload>

            <!-- URL Input -->
            <div class="grid grid-cols-1 gap-6 md:grid-cols-3">
              <div class="md:col-span-2">
                <label class="mb-2 block text-sm font-black text-text-main dark:text-white">Add Website Data Source</label>
                <el-input v-model="draft.website_source_input" size="large" placeholder="https://example.com/docs">
                  <template #prefix>
                    <span class="material-symbols-outlined text-[20px] text-slate-400">link</span>
                  </template>
                </el-input>
              </div>
              <div class="flex items-end">
                <el-button
                  type="default"
                  class="!h-[46px] !w-full !rounded-lg !font-black !bg-white dark:!bg-surface-dark !border-slate-200 dark:!border-slate-700"
                  @click="addSource"
                >
                  <span class="material-symbols-outlined text-[20px]">add</span>
                  Add Source
                </el-button>
              </div>
            </div>

            <div class="my-4 border-t border-slate-200 dark:border-slate-700"></div>

            <!-- Attached Documents List -->
            <div class="flex flex-col gap-4">
              <div class="flex items-center justify-between">
                <h3 class="text-lg font-black text-text-main dark:text-white">Attached Documents ({{ draft.knowledge.length }})</h3>
                <el-button text class="!p-0 text-sm font-black text-primary hover:text-primary/80" @click="ElMessage.info('Manage: coming soon')">
                  Manage All
                </el-button>
              </div>

              <div v-for="item in draft.knowledge" :key="item.id" class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-surface-light p-4 shadow-sm transition-all hover:shadow-md dark:border-slate-700 dark:bg-surface-dark"
                :class="item.type === 'file' && item.status === 'processing' ? 'border-primary/30 bg-primary/5 dark:bg-primary/5' : ''"
              >
                <div class="flex items-start justify-between gap-4">
                  <div class="flex items-center gap-4 min-w-0">
                    <div
                      class="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg"
                      :class="item.type === 'url' ? 'bg-purple-50 text-purple-500 dark:bg-purple-900/20' : (item.name.endsWith('.pdf') ? 'bg-red-50 text-red-500 dark:bg-red-900/20' : 'bg-blue-50 text-blue-500 dark:bg-blue-900/20')"
                    >
                      <span class="material-symbols-outlined">{{ item.type === 'url' ? 'language' : (item.name.endsWith('.pdf') ? 'picture_as_pdf' : 'description') }}</span>
                    </div>
                    <div class="min-w-0">
                      <p class="font-black text-text-main dark:text-white truncate">
                        {{ item.type === 'url' ? item.url : item.name }}
                      </p>
                      <p class="text-xs text-text-secondary dark:text-slate-400">
                        <template v-if="item.type === 'url'">{{ item.metaLabel }}</template>
                        <template v-else>
                          {{ item.sizeLabel }} • {{ item.status === 'processing' ? 'Parsing content...' : 'Uploaded just now' }}
                        </template>
                      </p>
                    </div>
                  </div>

                  <div class="flex items-center gap-2">
                    <span
                      v-if="item.type === 'url' || item.status === 'ready'"
                      class="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-bold text-green-800 dark:bg-green-900/30 dark:text-green-400"
                    >
                      {{ statusPill(item) }}
                    </span>
                    <el-button
                      circle
                      text
                      class="ab-icon-btn !text-slate-400 hover:!text-red-500"
                      @click="store.removeKnowledge(item.id)"
                    >
                      <span class="material-symbols-outlined text-[20px]">{{ item.type === 'file' && item.status === 'processing' ? 'close' : 'delete' }}</span>
                    </el-button>
                  </div>
                </div>

                <div v-if="item.type === 'file' && item.status === 'processing'" class="mt-1 flex items-center gap-3">
                  <el-progress :percentage="Number(item.progress || 0)" :stroke-width="8" :show-text="false" class="flex-1" />
                  <span class="text-xs font-black text-primary">{{ item.progress || 0 }}%</span>
                </div>
              </div>
            </div>

            <!-- Action Buttons -->
            <div class="mt-12 flex items-center justify-between pt-6">
              <el-button text class="!px-6 !py-3 !rounded-lg !font-black" @click="goBack">
                <span class="material-symbols-outlined text-[18px] mr-1">arrow_back</span>
                Back
              </el-button>
              <div class="flex items-center gap-4">
                <span class="text-xs font-bold text-text-secondary dark:text-slate-500">Auto-saved</span>
                <el-button type="primary" class="!px-8 !py-3 !rounded-lg !font-black" @click="goNext">
                  Continue
                  <span class="material-symbols-outlined text-[18px] ml-1">arrow_forward</span>
                </el-button>
              </div>
            </div>
          </div>
      </div>
    </el-main>
  </el-container>
</template>
