<script setup lang="ts">
const props = defineProps<{
  title: string
  subtitle: string
}>()
</script>

<template>
  <header
    class="px-6 py-5 border-b border-slate-200 dark:border-slate-800 bg-surface-light dark:bg-surface-dark flex justify-between items-center h-full"
  >
    <div class="min-w-0">
      <h2 class="text-3xl font-black tracking-tight text-text-main dark:text-white">
        {{ props.title }}
      </h2>
      <p class="text-text-secondary dark:text-slate-400 mt-1 truncate">
        {{ props.subtitle }}
      </p>
    </div>
    <div class="flex items-center gap-3 shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
