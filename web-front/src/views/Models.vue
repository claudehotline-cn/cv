<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>Models</span>
        <el-button size="small" @click="load" :loading="loading">刷新</el-button>
      </div>
    </template>
    <el-table :data="rows" height="480" style="width:100%">
      <el-table-column prop="id" label="ID" width="220" />
      <el-table-column prop="task" label="Task" width="100" />
      <el-table-column prop="family" label="Family" width="120" />
      <el-table-column prop="variant" label="Variant" width="120" />
      <el-table-column prop="path" label="Path" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listModels } from '@/api/cp'
const loading = ref(false)
const rows = ref<any[]>([])
async function load(){
  loading.value = true
  try{ const resp = await listModels(); rows.value = (resp as any).data || [] } finally { loading.value=false }
}
onMounted(load)
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
</style>

