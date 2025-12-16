<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeBaseApi } from '../api'

const router = useRouter()

interface KnowledgeBase {
  id: number
  name: string
  description: string
  document_count: number
  created_at: string
  is_active: boolean
}

const loading = ref(false)
const knowledgeBases = ref<KnowledgeBase[]>([])
const dialogVisible = ref(false)
const form = ref({
  name: '',
  description: ''
})

const loadData = async () => {
  loading.value = true
  try {
    const res = await knowledgeBaseApi.list()
    knowledgeBases.value = res.data.items
  } catch (err) {
    ElMessage.error('加载知识库列表失败')
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  try {
    await knowledgeBaseApi.create(form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    form.value = { name: '', description: '' }
    loadData()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '创建失败')
  }
}

const handleDelete = async (kb: KnowledgeBase) => {
  try {
    await ElMessageBox.confirm(`确定删除知识库 "${kb.name}" 吗？`, '确认删除', {
      type: 'warning'
    })
    await knowledgeBaseApi.delete(kb.id)
    ElMessage.success('删除成功')
    loadData()
  } catch (err) {
    // 用户取消
  }
}

const goToDetail = (kb: KnowledgeBase) => {
  router.push(`/knowledge-bases/${kb.id}`)
}

onMounted(loadData)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><FolderOpened /></el-icon>
        知识库管理
      </h1>
      <el-button type="primary" @click="dialogVisible = true">
        <el-icon><Plus /></el-icon>
        创建知识库
      </el-button>
    </div>

    <div class="card-grid" v-loading="loading">
      <div 
        v-for="kb in knowledgeBases" 
        :key="kb.id" 
        class="kb-card"
        @click="goToDetail(kb)"
      >
        <div class="kb-card-header">
          <div class="kb-card-icon">
            <el-icon size="32"><Collection /></el-icon>
          </div>
          <el-dropdown @click.stop trigger="click">
            <el-button text circle>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleDelete(kb)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <h3 class="kb-card-title">{{ kb.name }}</h3>
        <p class="kb-card-desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-card-footer">
          <span class="kb-card-stat">
            <el-icon><Document /></el-icon>
            {{ kb.document_count }} 个文档
          </span>
        </div>
      </div>

      <!-- 空状态 -->
      <el-empty v-if="!loading && knowledgeBases.length === 0" description="暂无知识库">
        <el-button type="primary" @click="dialogVisible = true">立即创建</el-button>
      </el-empty>
    </div>

    <!-- 创建对话框 -->
    <el-dialog v-model="dialogVisible" title="创建知识库" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="请输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="请输入描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-container {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  padding: 24px;
  background: rgba(30, 30, 46, 0.6);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  border: 1px solid rgba(137, 180, 250, 0.1);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #cdd6f4;
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  letter-spacing: 0.5px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 24px;
}

.kb-card {
  background: rgba(30, 30, 46, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(49, 50, 68, 0.8);
  border-radius: 16px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.kb-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, rgba(137, 180, 250, 0.1) 0%, transparent 100%);
  opacity: 0;
  transition: opacity 0.4s ease;
}

.kb-card:hover {
  border-color: rgba(137, 180, 250, 0.5);
  transform: translateY(-6px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.3);
}

.kb-card:hover::before {
  opacity: 1;
}

.kb-card-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(137, 180, 250, 0.2) 0%, rgba(203, 166, 247, 0.1) 100%);
  border-radius: 12px;
  color: #89b4fa;
  margin-bottom: 20px;
  transition: transform 0.4s ease;
}

.kb-card:hover .kb-card-icon {
  transform: scale(1.1) rotate(5deg);
}

.kb-card-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #bac2de;
  font-size: 13px;
  background: rgba(49, 50, 68, 0.5);
  padding: 6px 12px;
  border-radius: 20px;
}
</style>
