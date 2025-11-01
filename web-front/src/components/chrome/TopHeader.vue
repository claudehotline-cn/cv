<template>
  <div class="bar">
    <div class="brand">
      <el-icon size="20"><VideoCameraFilled /></el-icon>
      <span>VisionOps</span>
      <el-tag size="small" type="info" effect="dark" class="brand-tag">Control Plane</el-tag>
    </div>

    <el-input
      v-model="q"
      placeholder="搜索 Pipeline / Source / 模型..."
      clearable
      class="search"
      @keyup.enter="goSearch"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div class="actions">
      <el-tooltip content="切换主题">
        <el-switch v-model="dark" @change="toggleTheme" :active-color="`#22b2ff`"/>
      </el-tooltip>
      <el-tag size="small" :type="online ? 'success' : 'info'" effect="plain">{{ online ? 'Online' : 'Offline' }}</el-tag>
      <el-tag size="small" type="success" effect="plain">GPU: {{ gpuStat }}</el-tag>
      <el-tag size="small" type="warning" effect="plain">告警: {{ alerts }}</el-tag>
    </div>
  </div>
  <el-divider style="margin:0"/>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { VideoCameraFilled, Search } from '@element-plus/icons-vue'
const props = defineProps<{ collapsed?: boolean }>()
const emit = defineEmits(['toggle-aside'])

const q = ref('')
const dark = ref(true)
const router = useRouter()

function toggleTheme() {
  const root = document.documentElement
  if (dark.value) root.setAttribute('data-theme','dark')
  else root.setAttribute('data-theme','light')
  localStorage.setItem('va_theme', dark.value ? 'dark' : 'light')
}
onMounted(() => {
  const t = localStorage.getItem('va_theme') || 'dark'
  dark.value = (t === 'dark')
  toggleTheme()
})

function goSearch(){
  const keyword = q.value.trim()
  if (!keyword) return
  const lower = keyword.toLowerCase()
  let path = '/pipelines'
  let value = keyword
  if (lower.startsWith('source:')) {
    path = '/sources'
    value = keyword.slice('source:'.length).trim() || keyword
  } else if (lower.startsWith('model:')) {
    path = '/models'
    value = keyword.slice('model:'.length).trim() || keyword
  } else if (lower.startsWith('pipeline:')) {
    path = '/pipelines'
    value = keyword.slice('pipeline:'.length).trim() || keyword
  }
  router.push({ path, query: { q: value } })
}

const route = useRoute()

const app = useAppStore()
const online = computed(() => app.online)
const gpuStat = computed(() => app.system?.engine_runtime?.gpu_active ?? 'N/A')
const alerts = ref(0)
</script>

<style scoped>
.bar{ display:flex; align-items:center; gap:12px; height:64px; }
.brand{ display:flex; align-items:center; gap:8px; font-weight:600; color: var(--va-text-1); }
.brand span{ font-size:16px; letter-spacing:.2px; }
.brand-tag{ margin-left:8px; }
.search{ max-width: 520px; margin-left: 12px; }
.actions{ margin-left:auto; display:flex; align-items:center; gap:10px; }
.icon-btn{ width: 28px; height: 28px; padding: 0; }
</style>


