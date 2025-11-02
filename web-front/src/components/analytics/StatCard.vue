<script setup lang="ts">
const props = defineProps<{ title: string; value: string | number; sub?: string; trend?: 'up'|'down'|'flat'; trendText?: string }>()
</script>

<template>
  <div class="stat">
    <div class="title">{{ title }}</div>
    <div class="value">{{ value }}</div>
    <div v-if="sub || trendText" class="sub">
      <span v-if="trend==='up'" class="icon up">▲</span>
      <span v-else-if="trend==='down'" class="icon down">▼</span>
      <span v-else class="icon flat">━</span>
      <span class="text">{{ sub || trendText }}</span>
    </div>
  </div>
</template>

<style scoped>
.stat{ display:flex; flex-direction:column; gap:6px; }
.title{ font-size:12px; color: var(--va-text-2); }
.value{ font-size:22px; font-weight:700; color: var(--va-text-1); letter-spacing:.3px }
.sub{ font-size:12px; color: var(--va-text-2); display:flex; align-items:center; gap:6px }
.icon{ font-size:12px; }
.up{ color:#16c28a }
.down{ color:#ff8f6b }
.flat{ color: var(--va-text-2) }
</style>

