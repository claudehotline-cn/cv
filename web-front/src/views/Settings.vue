<template>
  <el-row :gutter="16">
    <el-col :span="12">
      <el-card>
        <template #header>引擎设置（/api/engine/set）</template>
        <el-form :model="engine" label-width="140px">
          <el-form-item label="use_nvdec"><el-switch v-model="engine.use_nvdec" /></el-form-item>
          <el-form-item label="use_nvenc"><el-switch v-model="engine.use_nvenc" /></el-form-item>
          <el-form-item label="use_multistage"><el-switch v-model="engine.use_multistage" /></el-form-item>
          <el-form-item label="render_cuda"><el-switch v-model="engine.render_cuda" /></el-form-item>
          <el-form-item label="use_cuda_nms"><el-switch v-model="engine.use_cuda_nms" /></el-form-item>
          <el-form-item label="overlay_thickness"><el-input-number v-model="engine.overlay_thickness" :min="0" :max="6" /></el-form-item>
          <el-form-item label="overlay_alpha"><el-input-number v-model="engine.overlay_alpha" :min="0" :max="1" :step="0.05" /></el-form-item>
          <el-form-item>
            <el-button type="primary" @click="apply" :loading="loading">应用</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </el-col>
    <el-col :span="12">
      <el-card>
        <template #header>控制面 ApplyPipeline（REST）</template>
        <el-input v-model="applyJson" type="textarea" :rows="14" placeholder="粘贴 overrides JSON (docs/examples/overrides_examples.json)" />
        <div style="margin-top:8px">
          <el-button @click="applyPipeline" :loading="loading">Apply</el-button>
          <el-button @click="applyPipelines" :loading="loading">Apply 批量</el-button>
          <el-link href="/docs/examples/rest_apply_overrides.md" target="_blank">示例文档</el-link>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { setEngine, applyPipeline as cpApply, applyPipelines as cpApplyBatch } from '@/api/cp'
const loading = ref(false)
const engine = ref({ use_nvdec: true, use_nvenc: true, use_multistage: true, render_cuda: true, use_cuda_nms: true, overlay_thickness: 3, overlay_alpha: 0.25 })
async function apply(){ loading.value = true; try{ await setEngine(engine.value as any) } finally { loading.value=false } }
const applyJson = ref('')
async function applyPipeline(){ if(!applyJson.value) return; loading.value=true; try{ await cpApply(JSON.parse(applyJson.value)) } finally{ loading.value=false } }
async function applyPipelines(){ if(!applyJson.value) return; loading.value=true; try{ const obj = JSON.parse(applyJson.value); const items = obj.items? obj.items : [obj.single_apply || obj]; await cpApplyBatch(items) } finally{ loading.value=false } }
</script>

