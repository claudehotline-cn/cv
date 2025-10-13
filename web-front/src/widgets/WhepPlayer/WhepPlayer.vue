<template>
  <div class="whep">
    <div class="mock-video" :class="{ active: playing }">
      <div class="noise"></div>
      <div class="label">{{ displayText }}</div>
    </div>
    <div class="controls">
      <slot name="right"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ whepUrl?: string; autoplay?: boolean }>(), {
  whepUrl: '',
  autoplay: true
})

const playing = ref(false)

watch(() => props.whepUrl, (val) => {
  playing.value = props.autoplay && !!val
})

function refresh() {
  playing.value = false
  requestAnimationFrame(() => {
    playing.value = props.autoplay && !!props.whepUrl
  })
}

defineExpose({ refresh })

const displayText = computed(() => props.whepUrl ? `Mock Stream · ${props.whepUrl}` : '未选择数据源')
</script>

<style scoped>
.whep{ position:relative; width:100%; padding-top:56.25%; background: #05070e; border-radius:10px; overflow:hidden; }
.mock-video{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#9dbad9; font-size:16px; letter-spacing:.4px; transition: all .3s ease; background: linear-gradient(135deg, rgba(34,178,255,.15), rgba(20,24,34,.9)); }
.mock-video .noise{ position:absolute; inset:0; background-image: repeating-linear-gradient(0deg, rgba(255,255,255,.05) 0, rgba(255,255,255,.05) 1px, transparent 1px, transparent 2px); opacity:.4; animation: noise 1.2s steps(10) infinite; }
.mock-video .label{ position:relative; z-index:1; padding:6px 14px; border-radius:20px; background: rgba(0,0,0,.45); border:1px solid rgba(255,255,255,.15); }
.mock-video.active{ box-shadow: 0 0 0 2px rgba(34,178,255,.25); }
.controls{ position:absolute; right:12px; bottom:12px; display:flex; gap:8px; z-index:2; }
@keyframes noise{ 0%{ transform:translateY(0);} 100%{ transform:translateY(-50%);} }
</style>

