<template>
  <el-row :gutter="16">
    <el-col :span="24">
      <el-card>
        <template #header>
          <div class="card-header">
            <span>Metrics (Prometheus)</span>
            <div>
              <el-switch v-model="auto" active-text="Auto" />
              <el-button size="small" @click="load">刷新</el-button>
            </div>
          </div>
        </template>
        <el-input type="textarea" :rows="20" v-model="text" />
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { http } from '@/api/http'
const text = ref('')
const auto = ref(true)
let timer: any = null
async function load(){ try{ text.value = await http.getText('/metrics') } catch(e){ text.value = String(e) } }
onMounted(()=>{ load(); timer = setInterval(()=>{ if(auto.value) load() }, 3000) })
onUnmounted(()=>{ if(timer) clearInterval(timer) })
</script>

<style scoped>
.card-header{ display:flex; align-items:center; justify-content:space-between; }
</style>

