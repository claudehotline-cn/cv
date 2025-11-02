<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VideoWall from '@/widgets/VideoWall/VideoWall.vue'

const route = useRoute()
const router = useRouter()

const items = computed(() => {
  const idsParam = (route.query.ids as string) || ''
  const one = (route.query.source as string) || ''
  const ids = (idsParam ? idsParam.split(',') : []).concat(one ? [one] : [])
  const uniq = Array.from(new Set(ids.filter(Boolean)))
  return uniq.map(id => ({ id, title: id }))
})

function back(){ router.back() }
</script>

<template>
  <div class="page">
    <el-page-header @back="back" content="Sources 预览 / 分析" />
    <div class="body">
      <VideoWall :items="items"/>
    </div>
  </div>
  
</template>

<style scoped>
.page{ padding: 4px; }
.body{ margin-top: 8px; }
</style>

