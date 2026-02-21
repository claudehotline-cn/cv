<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentBuilderStore } from '@/stores/agentBuilder'
import AgentBuilderSteps from '@/components/agent-builder/AgentBuilderSteps.vue'
import AgentBuilderHeader from '@/components/agent-builder/AgentBuilderHeader.vue'

const router = useRouter()
const store = useAgentBuilderStore()
const draft = computed(() => store.draft)

const schemaLines = computed(() => {
  const raw = String(draft.value.openapi_schema_text || '')
  return raw.split('\n')
})

function highlightLine(line: string): { key?: string; rest?: string; comment?: string } {
  const idx = line.indexOf('#')
  const comment = idx >= 0 ? line.slice(idx) : ''
  const code = idx >= 0 ? line.slice(0, idx) : line

  const m = code.match(/^(\s*[-\w\/.]+:)(\s+.*)?$/)
  if (!m) return { rest: code, comment }
  return { key: m[1], rest: m[2] || '', comment }
}

function goBack() {
  router.push('/agents/create/identity')
}

function goNext() {
  router.push('/agents/create/knowledge')
}

function importSchema() {
  ElMessage.info('Import schema: coming soon')
}

function saveDraft() {
  ElMessage.success('Draft saved (mock)')
}
</script>

<template>
  <el-container class="ab-root bg-background-light dark:bg-background-dark text-text-main dark:text-white h-full overflow-hidden">
    <el-header height="88px" class="!p-0">
      <AgentBuilderHeader
        title="Capabilities"
        subtitle="Configure what tools and skills your agent can use to perform tasks."
      >
        <template #actions>
          <el-button text class="!font-black" @click="saveDraft">Save Draft</el-button>
        </template>
      </AgentBuilderHeader>
    </el-header>

    <el-main class="!p-0 flex-1 min-w-0 min-h-0 overflow-y-auto bg-background-light dark:bg-background-dark">
      <div class="p-6 lg:p-8 pb-12">
        <div class="w-full flex flex-col gap-7">
          <div class="ab-steps-panel w-full">
            <AgentBuilderSteps />
          </div>

          <!-- Built-in Tools -->
          <section class="flex flex-col gap-5">
            <h2 class="text-xl font-black flex items-center gap-2">
              <span class="material-symbols-outlined text-primary">build_circle</span>
              Built-in Tools
            </h2>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div class="group relative flex flex-col gap-4 rounded-xl border border-border-color bg-surface-light dark:bg-surface-dark p-5 shadow-sm hover:shadow-md transition-shadow">
                <div class="flex justify-between items-start">
                  <div class="size-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center text-blue-600 dark:text-blue-400">
                    <span class="material-symbols-outlined">public</span>
                  </div>
                  <el-switch v-model="draft.tools.web_search" />
                </div>
                <div>
                  <h3 class="font-black text-lg mb-1">Web Search</h3>
                  <p class="text-text-secondary text-sm leading-relaxed">
                    Allow the agent to browse the internet for real-time information and current events.
                  </p>
                </div>
              </div>

              <div class="group relative flex flex-col gap-4 rounded-xl border border-border-color bg-surface-light dark:bg-surface-dark p-5 shadow-sm hover:shadow-md transition-shadow">
                <div class="flex justify-between items-start">
                  <div class="size-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center text-purple-600 dark:text-purple-400">
                    <span class="material-symbols-outlined">terminal</span>
                  </div>
                  <el-switch v-model="draft.tools.code_interpreter" />
                </div>
                <div>
                  <h3 class="font-black text-lg mb-1">Code Interpreter</h3>
                  <p class="text-text-secondary text-sm leading-relaxed">
                    Enable Python code execution for complex data analysis, math, and logic.
                  </p>
                </div>
              </div>

              <div class="group relative flex flex-col gap-4 rounded-xl border border-border-color bg-surface-light dark:bg-surface-dark p-5 shadow-sm hover:shadow-md transition-shadow">
                <div class="flex justify-between items-start">
                  <div class="size-10 rounded-lg bg-pink-50 dark:bg-pink-900/20 flex items-center justify-center text-pink-600 dark:text-pink-400">
                    <span class="material-symbols-outlined">image</span>
                  </div>
                  <el-switch v-model="draft.tools.image_generation" />
                </div>
                <div>
                  <h3 class="font-black text-lg mb-1">Image Generation</h3>
                  <p class="text-text-secondary text-sm leading-relaxed">
                    Create images from text descriptions using DALL-E or Stable Diffusion models.
                  </p>
                </div>
              </div>
            </div>
          </section>

          <hr class="border-border-color" />

          <!-- Custom API Tools -->
          <section class="flex flex-col gap-5">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div class="flex flex-col">
                <h2 class="text-xl font-black flex items-center gap-2">
                  <span class="material-symbols-outlined text-primary">api</span>
                  Custom API Tools
                </h2>
              </div>
              <el-button
                type="default"
                class="!bg-white dark:!bg-surface-dark !border-slate-200 dark:!border-slate-700 !text-text-main"
                @click="importSchema"
              >
                <span class="material-symbols-outlined mr-2 text-base">upload_file</span>
                Import Schema
              </el-button>
            </div>

            <div class="rounded-xl border border-border-color dark:border-slate-700 bg-white dark:bg-[#1e1e1e] overflow-hidden shadow-sm flex flex-col h-[320px]">
              <div class="flex items-center justify-between px-4 py-2 border-b border-border-color dark:border-slate-700 bg-slate-50 dark:bg-[#252526]">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-mono text-slate-500">{{ draft.openapi_schema_name }}</span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] font-black bg-green-100 text-green-700 border border-green-200">VALID</span>
                </div>
                <div class="flex gap-1">
                  <div class="size-3 rounded-full bg-red-400"></div>
                  <div class="size-3 rounded-full bg-amber-400"></div>
                  <div class="size-3 rounded-full bg-green-400"></div>
                </div>
              </div>

              <div class="flex-1 overflow-auto p-4 font-mono text-sm leading-6 flex gap-4">
                <div class="flex flex-col text-right text-slate-300 dark:text-slate-600 select-none min-w-[24px]">
                  <span v-for="(_, idx) in schemaLines" :key="idx">{{ idx + 1 }}</span>
                </div>

                <div class="flex flex-col text-slate-800 dark:text-slate-300 w-full">
                  <div v-for="(line, idx) in schemaLines" :key="idx" class="whitespace-pre">
                    <template v-if="highlightLine(line).key">
                      <span class="text-fuchsia-500">{{ highlightLine(line).key }}</span>
                      <span class="text-emerald-600 dark:text-emerald-400">{{ highlightLine(line).rest }}</span>
                      <span class="text-slate-400">{{ highlightLine(line).comment }}</span>
                    </template>
                    <template v-else>
                      <span class="text-slate-800 dark:text-slate-300">{{ highlightLine(line).rest }}</span>
                      <span class="text-slate-400">{{ highlightLine(line).comment }}</span>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div class="flex items-center justify-end gap-3 pt-4 pb-12">
            <el-button type="default" class="!px-6 !py-2.5 !rounded-lg !font-black" @click="goBack">Back</el-button>
            <el-button type="primary" size="large" class="!px-8" @click="goNext">
              Next: Knowledge
              <span class="material-symbols-outlined ml-2">arrow_forward</span>
            </el-button>
          </div>
        </div>
      </div>
    </el-main>
  </el-container>
</template>
