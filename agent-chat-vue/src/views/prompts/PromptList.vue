<template>
  <el-container class="settings-layout">
    <el-header class="glass-panel header">
      <div class="header-content">
        <h2>Prompt 管理</h2>
        <div class="header-actions">
          <el-input
            v-model="searchKey"
            placeholder="搜索 key / name"
            clearable
            style="width: 240px"
            @clear="loadPrompts"
            @keyup.enter="loadPrompts"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="filterCategory" placeholder="分类" clearable style="width: 160px" @change="loadPrompts">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </div>
      </div>
    </el-header>

    <el-main>
      <div v-if="isLoading" class="loading-state">
        <el-skeleton :rows="5" animated />
      </div>

      <el-table v-else :data="prompts" stripe class="prompt-table" @row-click="goEdit">
        <el-table-column prop="key" label="Key" min-width="260">
          <template #default="{ row }">
            <span class="key-text">{{ row.key }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="200" />
        <el-table-column prop="category" label="分类" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.category" size="small" effect="plain">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Published" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.published_version" type="success" size="small" effect="dark">
              v{{ row.published_version.version }}
            </el-tag>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column label="Draft" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.draft_version" type="warning" size="small" effect="dark">
              v{{ row.draft_version.version }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total > pageSize" class="pagination-bar">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="loadPrompts"
        />
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '@/api/client'

const router = useRouter()
const prompts = ref<any[]>([])
const isLoading = ref(false)
const searchKey = ref('')
const filterCategory = ref('')
const total = ref(0)
const currentPage = ref(1)
const pageSize = 50

const categories = computed(() => {
  const set = new Set<string>()
  prompts.value.forEach(p => { if (p.category) set.add(p.category) })
  return Array.from(set).sort()
})

onMounted(() => loadPrompts())

async function loadPrompts() {
  isLoading.value = true
  try {
    const res = await apiClient.listPrompts({
      key: searchKey.value || undefined,
      category: filterCategory.value || undefined,
      limit: pageSize,
      offset: (currentPage.value - 1) * pageSize,
    })
    prompts.value = res.items
    total.value = res.total
  } catch (e) {
    ElMessage.error('加载 Prompt 列表失败')
    console.error(e)
  } finally {
    isLoading.value = false
  }
}

function goEdit(row: any) {
  router.push(`/agents/prompts/${row.id}`)
}
</script>

<style scoped>
.settings-layout { height: 100vh; background: var(--bg-primary); overflow-y: auto; }
.header { padding: 40px 0; height: auto !important; background: transparent !important; border-bottom: 1px solid var(--border-color); }
.header-content { max-width: 1200px; margin: 0 auto; padding: 0 24px; display: flex; justify-content: space-between; align-items: center; }
.header h2 { font-size: 32px; background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
.header-actions { display: flex; gap: 12px; align-items: center; }
.prompt-table { cursor: pointer; }
.key-text { font-family: monospace; font-size: 13px; color: var(--el-color-primary); }
.text-muted { color: var(--text-tertiary); font-size: 12px; }
.pagination-bar { display: flex; justify-content: center; padding: 24px 0; }
</style>
