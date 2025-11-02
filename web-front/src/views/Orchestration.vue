<template>
  <div class="page">
    <el-card class="card">
      <template #header>编排操作</template>
      <el-form :model="form" label-width="120px" class="form">
        <el-form-item label="Source ID"><el-input v-model="form.id" placeholder="cam_01"/></el-form-item>
        <el-form-item label="RTSP URI"><el-input v-model="form.uri" placeholder="rtsp://127.0.0.1:8554/camera_01"/></el-form-item>
        <el-form-item label="Pipeline 名称"><el-input v-model="form.pipeline_name" placeholder="pipeline_demo"/></el-form-item>
        <el-form-item label="YAML 路径"><el-input v-model="form.yaml_path" placeholder="D:/.../graphs/analyzer_multistage_example.yaml"/></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loadingApply" @click="onAttachApply">Attach + Apply</el-button>
          <el-button type="danger" :loading="loadingRemove" @click="onDetachRemove">Detach + Remove</el-button>
          <span class="msg" v-if="msg">{{ msg }}</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="card">
      <template #header>健康概览</template>
      <div class="health">
        <el-statistic title="VSM 源总数" :value="health?.vsm?.total || 0"/>
        <el-statistic title="VSM 运行中" :value="health?.vsm?.running || 0"/>
        <el-statistic title="VA Models" :value="health?.va?.data?.model_count || 0"/>
        <el-statistic title="VA Pipeline 运行数" :value="healthPipelinesRunning"/>
      </div>
      <div class="va-brief" v-if="health?.va?.data">
        <div>Engine: {{ health?.va?.data?.engine?.type }} / provider={{ health?.va?.data?.engine_runtime?.provider }}</div>
        <div>DB: {{ health?.va?.data?.database?.driver }}@{{ health?.va?.data?.database?.host }}:{{ health?.va?.data?.database?.port }}</div>
      </div>
      <el-button @click="refreshHealth" :loading="loadingHealth">刷新</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { orchAttachApply, orchDetachRemove, orchHealth } from '@/api/vsm'

const form = ref({ id: '', uri: '', pipeline_name: '', yaml_path: '' })
const loadingApply = ref(false)
const loadingRemove = ref(false)
const msg = ref('')

async function onAttachApply(){
  msg.value=''
  loadingApply.value = true
  try { await orchAttachApply({ id: form.value.id, uri: form.value.uri, pipeline_name: form.value.pipeline_name, yaml_path: form.value.yaml_path })
    msg.value = 'Attach+Apply 成功' } catch(e:any){ msg.value = e?.message || '失败' } finally { loadingApply.value=false }
}
async function onDetachRemove(){
  msg.value=''
  loadingRemove.value=true
  try { await orchDetachRemove({ id: form.value.id, pipeline_name: form.value.pipeline_name })
    msg.value='Detach+Remove 成功' } catch(e:any){ msg.value=e?.message||'失败' } finally { loadingRemove.value=false }
}

const health = ref<any>(null)
const loadingHealth = ref(false)
const healthPipelinesRunning = computed(()=>{
  const d = health.value?.va?.data
  const agg = d?.system_stats?.running_pipelines || d?.pipelines_running || 0
  return agg
})
async function refreshHealth(){
  loadingHealth.value=true
  try { health.value = await orchHealth() } finally { loadingHealth.value=false }
}
refreshHealth()
</script>

<style scoped>
.page{ display: grid; gap: 16px; align-content: start; }
.card{ }
.form{ max-width: 720px; }
.msg{ margin-left: 12px; opacity: .8; }
.health{ display: grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom: 8px; }
.va-brief{ color: var(--va-text-2); margin-bottom: 8px; }
</style>

