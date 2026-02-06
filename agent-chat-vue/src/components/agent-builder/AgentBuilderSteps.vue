<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = withDefaults(
  defineProps<{
    direction?: 'horizontal' | 'vertical'
  }>(),
  {
    direction: 'horizontal',
  }
)

type StepKey = 'identity' | 'capabilities' | 'knowledge' | 'review'

const route = useRoute()

const steps = [
  {
    key: 'identity' as StepKey,
    title: 'Identity',
    description: 'Basic info & avatar',
    path: '/agents/create/identity',
  },
  {
    key: 'capabilities' as StepKey,
    title: 'Capabilities',
    description: 'Tools & skills',
    path: '/agents/create/capabilities',
  },
  {
    key: 'knowledge' as StepKey,
    title: 'Knowledge',
    description: 'Files & resources',
    path: '/agents/create/knowledge',
  },
  {
    key: 'review' as StepKey,
    title: 'Review',
    description: 'Publish agent',
    path: '/agents/create/review',
  },
]

const activeIndex = computed(() => {
  const p = String(route.path || '')
  const idx = steps.findIndex((s) => p === s.path)
  return idx >= 0 ? idx : 0
})
</script>

<template>
  <div class="ab-steps">
    <el-steps :direction="props.direction" :active="activeIndex" process-status="process" finish-status="success" align-center>
      <el-step v-for="s in steps" :key="s.key" :title="s.title" />
    </el-steps>
  </div>
</template>
