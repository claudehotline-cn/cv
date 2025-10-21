<template>
  <el-row :gutter="16">
    <el-col :span="8">
      <el-card shadow="hover" @click="$router.push('/observability/metrics')" class="nav-card">
        <template #header><strong>Metrics</strong></template>
        <div>查看系统与 Pipeline 指标曲线</div>
      </el-card>
    </el-col>
    <el-col :span="8">
      <el-card shadow="hover" @click="$router.push('/observability/logs')" class="nav-card">
        <template #header><strong>Logs</strong></template>
        <div>实时日志、过滤、导出与跟随</div>
      </el-card>
    </el-col>
    <el-col :span="8">
      <el-card shadow="hover" @click="$router.push('/observability/events')" class="nav-card">
        <template #header><strong>Events</strong></template>
        <div>系统/Pipeline 事件与告警</div>
      </el-card>
    </el-col>
  </el-row>

  <el-row :gutter="16" style="margin-top:12px">
    <el-col :span="8">
      <el-card shadow="hover" @click="$router.push('/observability/sessions')" class="nav-card">
        <template #header><strong>Sessions</strong></template>
        <div>会话生命周期（订阅/取消/失败）</div>
      </el-card>
    </el-col>
  </el-row>

  <el-row :gutter="16" style="margin-top:12px">
    <el-col :span="24">
      <el-card>
        <template #header>
          <div class="card-header">
            <span>Metrics (Prometheus 原始)</span>
            <div>
              <el-switch v-model="auto" active-text="自动刷新" />
              <el-button size="small" @click="load">刷新</el-button>
            </div>
          </div>
        </template>
        <el-input type="textarea" :rows="20" v-model="text" />
      </el-card>
    </el-col>
  </el-row>

  <el-row :gutter="16" style="margin-top:12px">
    <el-col :span="24">
      <el-card>
        <template #header>
          <div class="card-header">
            <span>System Info</span>
            <div>
              <el-button size="small" @click="loadSys">刷新</el-button>
            </div>
          </div>
        </template>
        <div class="sys-grid">
          <div><strong>Engine:</strong> {{ sys?.engine?.type }} #{{ sys?.engine?.device }}</div>
          <div><strong>Subscriptions heavy_slots:</strong> {{ sys?.subscriptions?.heavy_slots }}</div>
          <div><strong>Subscriptions model_slots:</strong> {{ sys?.subscriptions?.model_slots }}</div>
          <div><strong>Subscriptions rtsp_slots:</strong> {{ sys?.subscriptions?.rtsp_slots }}</div>
          <div><strong>Subscriptions max_queue:</strong> {{ sys?.subscriptions?.max_queue }}</div>
          <div><strong>Subscriptions ttl_seconds:</strong> {{ sys?.subscriptions?.ttl_seconds }}</div>
          <div><strong>WHEP Base:</strong> {{ sys?.sfu?.whep_base }}</div>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { http } from '@/api/http'
import { getSystemInfo } from '@/api/cp'
const text = ref('')
const auto = ref(true)
let timer: any = null
async function load(){ try{ text.value = await http.getText('/metrics') } catch(e){ text.value = String(e) } }
onMounted(()=>{ load(); timer = setInterval(()=>{ if(auto.value) load() }, 3000) })
onUnmounted(()=>{ if(timer) clearInterval(timer) })

const sys = ref<any>(null)
async function loadSys(){ try{ const r:any = await getSystemInfo(); sys.value = r?.data || r } catch(e) { sys.value = { error: String(e) } } }
onMounted(()=>{ loadSys() })
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
.nav-card{ cursor: pointer; user-select:none }
.sys-grid{ display:grid; grid-template-columns: repeat(2, minmax(200px, 1fr)); gap:8px; font-size:13px; }
</style>
