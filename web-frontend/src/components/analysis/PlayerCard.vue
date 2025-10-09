<template>
  <div class="va-player-card" :class="{ 'is-connecting': connecting, 'is-error': error }">
    <div class="va-player-header">
      <div class="va-player-title">
        <span class="va-dot" :class="statusClass" />
        <span class="va-title-text">{{ title }}</span>
      </div>
      <div class="va-player-badges">
        <el-tag size="small" effect="dark" type="info" v-if="stats?.resolution">{{ stats.resolution }}</el-tag>
        <el-tag size="small" effect="dark" :type="connected ? 'success' : (connecting ? 'warning' : 'danger')">
          {{ connected ? '已连接' : (connecting ? '连接中' : '未连接') }}
        </el-tag>
        <el-tag size="small" effect="dark" v-if="stats?.fps !== undefined">FPS: {{ stats.fps }}</el-tag>
      </div>
    </div>

    <div class="va-player-body">
      <slot />
      <div class="va-player-overlay" v-if="connecting || error">
        <template v-if="connecting">
          <el-icon class="va-spin"><Loading /></el-icon>
          <span>正在连接...</span>
        </template>
        <template v-else>
          <el-icon><WarningFilled /></el-icon>
          <span>连接失败</span>
        </template>
      </div>
    </div>

    <div class="va-player-controls">
      <el-tooltip content="播放/暂停" placement="top">
        <el-button circle size="small" @click="$emit('play-pause')">
          <el-icon><VideoPlay /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip content="静音/取消" placement="top">
        <el-button circle size="small" @click="$emit('toggle-mute')">
          <el-icon><Bell /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip content="截图" placement="top">
        <el-button circle size="small" @click="$emit('screenshot')">
          <el-icon><Camera /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip content="全屏" placement="top">
        <el-button circle size="small" @click="$emit('fullscreen')">
          <el-icon><FullScreen /></el-icon>
        </el-button>
      </el-tooltip>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { computed } from 'vue'
import { ElTag, ElButton, ElTooltip, ElIcon } from 'element-plus'
import { Loading, WarningFilled, Camera, Bell, FullScreen, VideoPlay } from '@element-plus/icons-vue'

const props = defineProps<{
  title?: string
  connected?: boolean
  connecting?: boolean
  error?: boolean
  stats?: { fps?: number; resolution?: string }
}>()

defineEmits(['toggle-mute', 'play-pause', 'screenshot', 'fullscreen'])
const statusClass = computed(() => {
  if (props.connected) return 'ok'
  if (props.connecting) return 'warn'
  return 'err'
})
</script>

<style scoped>
.va-player-card {
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--va-card-bg, #0f172a);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.06);
}
.va-player-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--va-card-header-bg, #111827);
}
.va-player-title { display: flex; align-items: center; gap: 8px; }
.va-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.va-dot.ok { background: #22c55e; }
.va-dot.warn { background: #f59e0b; }
.va-dot.err { background: #ef4444; }
.va-title-text { color: #e5e7eb; font-weight: 600; }
.va-player-badges .el-tag { margin-left: 6px; }

.va-player-body { position: relative; background: #000; aspect-ratio: 16/9; }
.va-player-body ::v-deep video, .va-player-body video {
  width: 100%; height: 100%; object-fit: contain; display: block;
}
.va-player-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; color: #e5e7eb; background: rgba(0,0,0,0.35);
}
.va-spin { animation: va-rot 1s linear infinite; }
@keyframes va-rot { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }

.va-player-controls {
  display: flex; align-items: center; gap: 8px; padding: 8px; justify-content: center; background: var(--va-card-header-bg, #111827);
}

.is-error .va-player-body { filter: grayscale(0.2) brightness(0.8); }
</style>
