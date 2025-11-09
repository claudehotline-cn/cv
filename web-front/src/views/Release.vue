<template>
  <el-card shadow="hover">
    <template #header>
      <div class="card-header">
        <div>
          <span class="title">发布/切换</span>
          <span class="subtitle">SetEngine + HotSwap</span>
        </div>
      </div>
    </template>

    <el-form :model="form" label-width="160px" size="small" class="form">
      <el-form-item label="Pipeline 名">
        <el-input v-model="form.pipeline_name" placeholder="det" />
      </el-form-item>
      <el-form-item label="模型节点名">
        <el-input v-model="form.node" placeholder="model" />
      </el-form-item>
      <el-form-item label="使用 Triton (Ensemble)">
        <el-switch v-model="form.use_triton" />
      </el-form-item>
      <el-form-item v-if="form.use_triton" label="Triton 模型名">
        <el-input v-model="form.triton_model" placeholder="ens_det_trt_full" />
      </el-form-item>
      <el-form-item v-if="form.use_triton" label="Triton 版本">
        <el-input v-model="form.triton_version" placeholder="(空=latest)" />
      </el-form-item>
      <el-form-item v-else label="模型 URI (本地/仓库)">
        <el-input v-model="form.model_uri" placeholder="models/yolov12x.onnx 或 .engine" />
      </el-form-item>
      <el-form-item>
        <el-space>
          <el-button type="primary" :loading="loading" @click="doRelease">发布</el-button>
          <el-button :loading="loading" @click="reset">重置</el-button>
        </el-space>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cp, setEngineControl } from '@/api/cp'

const loading = ref(false)
const form = ref({
  pipeline_name: 'det',
  node: 'model',
  use_triton: true,
  triton_model: 'ens_det_trt_full',
  triton_version: '',
  model_uri: ''
})

async function doRelease(){
  loading.value = true
  try {
    if (form.value.use_triton) {
      await cp.release({ pipeline_name: form.value.pipeline_name, node: form.value.node, triton_model: form.value.triton_model, triton_model_version: form.value.triton_version || '' })
    } else {
      if (!form.value.model_uri) { ElMessage.warning('请填写模型 URI'); return }
      await cp.release({ pipeline_name: form.value.pipeline_name, node: form.value.node, model_uri: form.value.model_uri })
    }
    ElMessage.success('发布成功')
  } catch (e:any) {
    ElMessage.error(e?.message || '发布失败')
  } finally {
    loading.value = false
  }
}

function reset(){
  form.value = { pipeline_name: 'det', node: 'model', use_triton: true, triton_model: 'ens_det_trt_full', triton_version: '', model_uri: '' }
}
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
.title{ font-weight:600; color: var(--va-text-1); }
.subtitle{ font-size:12px; color: var(--va-text-2); margin-left:6px; }
.form{ max-width: 720px }
</style>
