<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentBuilderStore } from '@/stores/agentBuilder'

const router = useRouter()
const store = useAgentBuilderStore()
const draft = computed(() => store.draft)

const promptCount = computed(() => (draft.value.system_prompt || '').length)
const avatarUrl = computed(() => draft.value.avatar_data_url)

async function onAvatarChanged(uploadFile: any) {
  const raw = uploadFile?.raw as File | undefined
  if (!raw) return
  await onPickAvatar(raw)
}

async function onPickAvatar(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('Please select an image file')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('Max file size is 2MB')
    return
  }
  await store.setAvatarFromFile(file)
}

function goNext() {
  router.push('/agents/create/capabilities')
}

function cancel() {
  router.push('/chat/custom-agents')
}

function goDashboard() {
  router.push('/')
}
</script>

<template>
  <el-container class="ab-root h-screen overflow-hidden selection:bg-primary/30">
    <!-- Left Sidebar: Stepper -->
    <el-aside
      class="w-72 bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between shrink-0 z-10 shadow-sm"
    >
      <div class="p-6 flex flex-col gap-8">
        <!-- Header -->
        <div class="flex items-center gap-3">
          <div
            class="h-8 w-8 bg-primary rounded-lg flex items-center justify-center text-white font-bold text-lg"
            aria-hidden="true"
          >
            A
          </div>
          <div>
            <h1 class="text-base font-bold leading-none text-text-main dark:text-white">Agent Builder</h1>
            <span class="text-xs text-text-secondary">v2.0.1</span>
          </div>
        </div>

        <!-- Stepper Navigation -->
        <nav class="flex flex-col gap-2">
          <div class="text-xs font-semibold uppercase tracking-wider text-text-secondary mb-2 px-3">Wizard Steps</div>

          <div class="flex items-center gap-3 px-3 py-3 rounded-xl bg-primary/10 border border-primary/20">
            <span class="material-symbols-outlined text-primary">account_circle</span>
            <div class="flex flex-col">
              <span class="text-sm font-bold text-text-main dark:text-white">Identity</span>
              <span class="text-xs text-text-secondary">Basic info &amp; avatar</span>
            </div>
          </div>

          <el-button
            text
            class="!h-auto !p-0 !w-full"
            @click="goNext"
          >
            <div class="flex items-center gap-3 px-3 py-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800 transition-all group text-left w-full">
              <span class="material-symbols-outlined text-gray-400 group-hover:text-text-main transition-colors">bolt</span>
              <div class="flex flex-col">
                <span class="text-sm font-medium text-gray-500 group-hover:text-text-main transition-colors">Capabilities</span>
                <span class="text-xs text-gray-400">Tools &amp; skills</span>
              </div>
            </div>
          </el-button>

          <el-button text class="!h-auto !p-0 !w-full" @click="router.push('/agents/create/knowledge')">
            <div class="flex items-center gap-3 px-3 py-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800 transition-all group text-left w-full">
              <span class="material-symbols-outlined text-gray-400 group-hover:text-text-main transition-colors">menu_book</span>
              <div class="flex flex-col">
                <span class="text-sm font-medium text-gray-500 group-hover:text-text-main transition-colors">Knowledge</span>
                <span class="text-xs text-gray-400">Files &amp; resources</span>
              </div>
            </div>
          </el-button>

          <el-button text class="!h-auto !p-0 !w-full" @click="router.push('/agents/create/review')">
            <div class="flex items-center gap-3 px-3 py-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800 transition-all group text-left w-full">
              <span class="material-symbols-outlined text-gray-400 group-hover:text-text-main transition-colors">check_circle</span>
              <div class="flex flex-col">
                <span class="text-sm font-medium text-gray-500 group-hover:text-text-main transition-colors">Review</span>
                <span class="text-xs text-gray-400">Deploy agent</span>
              </div>
            </div>
          </el-button>
        </nav>
      </div>

      <div class="p-6 border-t border-slate-100 dark:border-slate-800">
        <el-button
          text
          class="!h-auto !p-0 flex items-center gap-2 text-text-secondary hover:text-text-main text-sm font-medium transition-colors"
          @click="goDashboard"
        >
          <span class="material-symbols-outlined text-[18px]">arrow_back</span>
          Back to Dashboard
        </el-button>
      </div>
    </el-aside>

    <!-- Main Content: Form -->
    <el-main class="!p-0 flex-1 overflow-y-auto relative scroll-smooth">
      <div class="max-w-4xl mx-auto px-10 py-12 flex flex-col gap-8 h-full min-h-screen">
        <!-- Page Header -->
        <div class="flex flex-col gap-2">
          <h2 class="text-3xl font-bold tracking-tight text-text-main dark:text-white">Identity</h2>
          <p class="text-text-secondary text-lg max-w-xl">
            Define your AI agent's core personality, name, and visual representation.
          </p>
        </div>
        <div class="w-full h-px bg-slate-200 dark:bg-slate-700"></div>

        <form class="flex flex-col gap-8 pb-20" @submit.prevent>
          <!-- Agent Name Input -->
          <div class="flex flex-col gap-3">
            <label class="text-sm font-bold text-text-main dark:text-white uppercase tracking-wide" for="agent-name">
              Agent Name
            </label>
            <el-input
              id="agent-name"
              v-model="draft.name"
              size="large"
              placeholder="e.g. Customer Support Bot, Creative Writer..."
              style="max-width: 44rem"
            />
            <p class="text-sm text-text-secondary">This name will be visible to users interacting with the agent.</p>
          </div>

          <!-- Avatar Section -->
          <div class="flex flex-col gap-3">
            <span class="text-sm font-bold text-text-main dark:text-white uppercase tracking-wide">Avatar</span>
            <div
              class="flex flex-col sm:flex-row items-start sm:items-center gap-6 p-6 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 bg-white/50 dark:bg-slate-800/30"
            >
              <div class="relative group">
                <div
                  class="h-24 w-24 rounded-full overflow-hidden ring-4 ring-white dark:ring-slate-800 shadow-md bg-slate-100 flex items-center justify-center"
                >
                  <img
                    v-if="avatarUrl"
                    :src="avatarUrl"
                    alt="Agent avatar"
                    class="h-full w-full object-cover"
                  />
                  <span v-else class="material-symbols-outlined text-slate-400 text-3xl">person</span>
                </div>

                <el-upload
                  class="absolute bottom-0 right-0"
                  action=""
                  :show-file-list="false"
                  :auto-upload="false"
                  accept="image/png,image/jpeg"
                  :on-change="onAvatarChanged"
                >
                  <el-button
                    circle
                    type="primary"
                    class="!h-8 !w-8 !p-0 !text-white !shadow-sm"
                    aria-label="Edit avatar"
                  >
                    <span class="material-symbols-outlined text-[18px]">edit</span>
                  </el-button>
                </el-upload>
              </div>

              <div class="flex flex-col gap-3">
                <div>
                  <h4 class="font-bold text-text-main dark:text-white">Agent Icon</h4>
                  <p class="text-sm text-text-secondary">Upload a JPG or PNG. Max size 2MB.</p>
                </div>
                <div class="flex gap-3">
                  <el-upload
                    action=""
                    :show-file-list="false"
                    :auto-upload="false"
                    accept="image/png,image/jpeg"
                    :on-change="onAvatarChanged"
                  >
                    <el-button
                      type="default"
                      class="!bg-white dark:!bg-slate-800 !border-slate-300 dark:!border-slate-600"
                    >
                      Upload Image
                    </el-button>
                  </el-upload>
                  <el-button text type="danger" class="!font-black" @click="store.removeAvatar">Remove</el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- System Prompt Input -->
          <div class="flex flex-col gap-3 flex-1">
            <div class="flex items-center justify-between" style="max-width: 48rem">
              <label
                class="text-sm font-bold text-text-main dark:text-white uppercase tracking-wide"
                for="system-prompt"
              >
                System Prompt / Instructions
              </label>
              <el-button text class="!p-0 text-primary text-sm font-bold hover:underline flex items-center gap-1" @click="ElMessage.info('Coming soon')">
                <span class="material-symbols-outlined text-[16px]">auto_awesome</span>
                Generate with AI
              </el-button>
            </div>
            <div class="relative" style="max-width: 48rem">
              <el-input
                id="system-prompt"
                v-model="draft.system_prompt"
                type="textarea"
                :rows="12"
                placeholder="You are a helpful customer support assistant..."
              />
              <div
                class="absolute bottom-3 right-3 text-xs text-gray-400 bg-white/80 dark:bg-slate-800/80 px-2 py-1 rounded"
              >
                {{ promptCount }} / 2000 chars
              </div>
            </div>
            <p class="text-sm text-text-secondary">Detailed instructions on how your agent should behave, speak, and reason.</p>
          </div>

          <!-- Actions -->
          <div
            class="flex items-center gap-4 mt-4 pt-6 border-t border-slate-200 dark:border-slate-700"
            style="max-width: 48rem"
          >
            <el-button text class="!px-6 !py-3 !rounded-lg !font-black" @click="cancel">Cancel</el-button>
            <div class="flex-1"></div>
            <el-button type="primary" size="large" class="!px-8" @click="goNext">
              Next: Capabilities
              <span class="material-symbols-outlined ml-2">arrow_forward</span>
            </el-button>
          </div>
        </form>
      </div>
    </el-main>

    <!-- Right Sidebar: Live Preview -->
    <el-aside
      class="w-[360px] bg-surface-light dark:bg-surface-dark border-l border-slate-200 dark:border-slate-800 hidden xl:flex flex-col shrink-0"
    >
      <div class="p-6 border-b border-slate-100 dark:border-slate-800 bg-surface-light dark:bg-surface-dark z-10">
        <h3 class="font-bold text-text-main dark:text-white flex items-center gap-2">
          <span class="material-symbols-outlined text-primary">visibility</span>
          Live Preview
        </h3>
        <p class="text-sm text-text-secondary mt-1">See how your agent looks to users</p>
      </div>

      <div
        class="flex-1 p-6 bg-slate-50 dark:bg-[#0d191c] overflow-y-auto flex flex-col items-center justify-start pt-12"
      >
        <div
          class="w-full bg-white dark:bg-slate-800 rounded-2xl shadow-xl border border-slate-100 dark:border-slate-700 overflow-hidden"
        >
          <div class="bg-primary/5 p-4 flex items-center gap-3 border-b border-slate-100 dark:border-slate-700">
            <div class="relative">
              <div class="h-10 w-10 rounded-full overflow-hidden bg-slate-200 flex items-center justify-center">
                <img v-if="avatarUrl" :src="avatarUrl" alt="Avatar preview" class="h-full w-full object-cover" />
                <span v-else class="material-symbols-outlined text-slate-500">smart_toy</span>
              </div>
              <div class="absolute bottom-0 right-0 h-3 w-3 bg-green-500 rounded-full border-2 border-white dark:border-slate-800"></div>
            </div>
            <div>
              <div class="font-bold text-sm text-text-main dark:text-white">{{ draft.name || 'Agent' }}</div>
              <div class="text-xs text-primary font-bold">Online</div>
            </div>
            <div class="ml-auto text-gray-400">
              <span class="material-symbols-outlined text-[20px]">more_vert</span>
            </div>
          </div>

          <div class="p-4 flex flex-col gap-4 min-h-[300px]">
            <div class="text-center text-xs text-gray-400 my-2">Today 9:41 AM</div>
            <div class="flex gap-3">
              <div class="h-8 w-8 rounded-full overflow-hidden bg-slate-200 flex-shrink-0 mt-1 flex items-center justify-center">
                <img v-if="avatarUrl" :src="avatarUrl" alt="Avatar" class="h-full w-full object-cover" />
                <span v-else class="material-symbols-outlined text-slate-500">smart_toy</span>
              </div>
              <div
                class="bg-slate-100 dark:bg-slate-700 p-3 rounded-2xl rounded-tl-none text-sm text-text-main dark:text-white max-w-[85%] leading-relaxed"
              >
                Hello! I'm {{ draft.name || 'Support Bot' }}. How can I assist you today with your account or order?
              </div>
            </div>

            <div class="flex gap-3 flex-row-reverse">
              <div
                class="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold flex-shrink-0 mt-1"
              >
                YOU
              </div>
              <div
                class="bg-primary text-white p-3 rounded-2xl rounded-tr-none text-sm max-w-[85%] leading-relaxed shadow-sm shadow-primary/20"
              >
                Hi, I need help updating my billing information.
              </div>
            </div>

            <div class="flex gap-3 mt-auto">
              <div class="h-8 w-8 rounded-full overflow-hidden bg-slate-200 flex-shrink-0 flex items-center justify-center">
                <img v-if="avatarUrl" :src="avatarUrl" alt="Avatar" class="h-full w-full object-cover" />
                <span v-else class="material-symbols-outlined text-slate-500">smart_toy</span>
              </div>
              <div class="bg-slate-100 dark:bg-slate-700 px-4 py-3 rounded-2xl rounded-tl-none flex items-center gap-1">
                <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"></div>
                <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce delay-75"></div>
                <div class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce delay-150"></div>
              </div>
            </div>
          </div>

          <div class="p-3 border-t border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800">
            <div
              class="flex items-center gap-2 bg-slate-50 dark:bg-slate-900 rounded-full px-4 py-2 border border-slate-200 dark:border-slate-700"
            >
              <span class="material-symbols-outlined text-gray-400 text-[20px]">add_circle</span>
              <div class="flex-1 text-sm text-gray-400">Type a message...</div>
              <span class="material-symbols-outlined text-gray-400 text-[20px]">mic</span>
            </div>
          </div>
        </div>

        <div class="mt-6 p-4 rounded-xl bg-blue-50 dark:bg-slate-800 border border-blue-100 dark:border-slate-700 w-full">
          <div class="flex gap-3">
            <span class="material-symbols-outlined text-primary mt-0.5">info</span>
            <div>
              <h4 class="text-sm font-bold text-text-main dark:text-white">Preview Mode</h4>
              <p class="text-xs text-text-secondary mt-1 leading-relaxed">
                This preview updates in real-time as you modify the Identity settings on the left.
              </p>
            </div>
          </div>
        </div>
      </div>
    </el-aside>
  </el-container>
</template>
