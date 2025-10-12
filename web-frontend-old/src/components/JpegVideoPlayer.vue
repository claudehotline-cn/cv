<template>
  <div class="jpeg-video-player">
    <div class="video-container" :style="containerStyle">
      <!-- Canvas元素用于显示JPEG帧 -->
      <canvas
        ref="canvasRef"
        :width="canvasWidth"
        :height="canvasHeight"
        class="video-canvas"
      />

      <!-- 视频控制叠加层 -->
      <div class="video-overlay">
        <!-- 播放状态指示器 -->
        <div class="status-indicator">
          <el-tag
            :type="isPlaying ? 'success' : 'info'"
            size="small"
            effect="dark"
          >
            {{ isPlaying ? `播放中 ${fps.toFixed(1)}fps` : "等待数据" }}
          </el-tag>
        </div>

        <!-- 分析结果叠加显示 -->
        <div
          v-if="showDetections && currentDetections.length > 0"
          class="detections-overlay"
        >
          <div
            v-for="(detection, index) in currentDetections"
            :key="index"
            class="detection-box"
            :style="getDetectionBoxStyle(detection)"
          >
            <span class="detection-label">
              {{ detection.class_name }} ({{
                Math.round(detection.confidence * 100)
              }}%)
            </span>
          </div>
        </div>

        <!-- 视频信息显示 -->
        <div v-if="showVideoInfo" class="video-info">
          <div class="info-item">
            分辨率: {{ currentWidth }}x{{ currentHeight }}
          </div>
          <div class="info-item">帧率: {{ fps.toFixed(1) }} fps</div>
          <div class="info-item">已接收: {{ frameCount }} 帧</div>
          <div class="info-item">延迟: {{ latency }}ms</div>
        </div>
      </div>

      <!-- 无视频时的占位符 -->
      <div v-if="!hasReceivedFrame" class="no-video-placeholder">
        <el-icon size="60"><Camera /></el-icon>
        <p>等待JPEG视频流...</p>
        <p style="font-size: 12px; color: #999">通过WebRTC Data Channel传输</p>
      </div>
    </div>

    <!-- 控制按钮 -->
    <div v-if="showControls" class="controls">
      <el-button-group>
        <el-button
          size="small"
          :disabled="!hasReceivedFrame"
          @click="togglePlay"
        >
          <el-icon
            ><VideoPlay v-if="!isPlaying" /><VideoPause v-else
          /></el-icon>
        </el-button>

        <el-button
          size="small"
          :disabled="!hasReceivedFrame"
          @click="saveCurrentFrame"
        >
          <el-icon><Download /></el-icon>
          保存
        </el-button>

        <el-button size="small" @click="toggleDetections">
          <el-icon><View /></el-icon>
          {{ showDetections ? "隐藏" : "显示" }}检测
        </el-button>

        <el-button size="small" @click="toggleVideoInfo">
          <el-icon><InfoFilled /></el-icon>
          信息
        </el-button>
      </el-button-group>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import {
  Camera,
  VideoPlay,
  VideoPause,
  Download,
  View,
  InfoFilled,
} from "@element-plus/icons-vue";
import type { DetectionResult } from "@/types";

// Props
interface Props {
  width?: number;
  height?: number;
  showControls?: boolean;
  showDetections?: boolean;
  detections?: DetectionResult[];
}

const props = withDefaults(defineProps<Props>(), {
  width: 640,
  height: 480,
  showControls: true,
  showDetections: true,
  detections: () => [],
});

// Emits
const emit = defineEmits<{
  frameReceived: [width: number, height: number];
  error: [message: string];
}>();

// 响应式数据
const canvasRef = ref<HTMLCanvasElement | null>(null);
const isPlaying = ref(false);
const hasReceivedFrame = ref(false);
const showVideoInfo = ref(false);

// 视频统计信息
const frameCount = ref(0);
const fps = ref(0);
const latency = ref(0);
const currentWidth = ref(0);
const currentHeight = ref(0);
const currentDetections = ref<DetectionResult[]>([]);

// FPS计算
const fpsCalculator = {
  frameTimestamps: [] as number[],
  lastUpdateTime: 0,
};

// 计算属性
const canvasWidth = computed(() => props.width);
const canvasHeight = computed(() => props.height);

const containerStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
}));

// 方法
const updateDetections = (detections: DetectionResult[]) => {
  if (props.showDetections) {
    currentDetections.value = detections || [];
  }
};

const getDetectionBoxStyle = (detection: DetectionResult) => {
  // 将检测框坐标转换为Canvas上的相对位置
  const scaleX = props.width / currentWidth.value;
  const scaleY = props.height / currentHeight.value;

  return {
    left: `${detection.bbox.x * scaleX}px`,
    top: `${detection.bbox.y * scaleY}px`,
    width: `${detection.bbox.width * scaleX}px`,
    height: `${detection.bbox.height * scaleY}px`,
  };
};

const calculateFPS = () => {
  const now = performance.now();
  fpsCalculator.frameTimestamps.push(now);

  // 保留最近1秒的时间戳
  fpsCalculator.frameTimestamps = fpsCalculator.frameTimestamps.filter(
    (timestamp) => now - timestamp <= 1000,
  );

  // 每500ms更新一次FPS显示
  if (now - fpsCalculator.lastUpdateTime >= 500) {
    fps.value = fpsCalculator.frameTimestamps.length;
    fpsCalculator.lastUpdateTime = now;
  }
};

// 显示JPEG帧
const displayJpegFrame = (jpegData: ArrayBuffer) => {
  if (!canvasRef.value) return;

  try {
    const blob = new Blob([jpegData], { type: "image/jpeg" });
    const imageUrl = URL.createObjectURL(blob);

    const img = new Image();
    img.onload = () => {
      const canvas = canvasRef.value!;
      const ctx = canvas.getContext("2d")!;

      // 更新当前帧尺寸
      currentWidth.value = img.width;
      currentHeight.value = img.height;

      // 清除画布
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // 保持宽高比绘制图像
      const scale = Math.min(
        canvas.width / img.width,
        canvas.height / img.height,
      );
      const scaledWidth = img.width * scale;
      const scaledHeight = img.height * scale;
      const x = (canvas.width - scaledWidth) / 2;
      const y = (canvas.height - scaledHeight) / 2;

      ctx.drawImage(img, x, y, scaledWidth, scaledHeight);

      // 更新统计信息
      frameCount.value++;
      calculateFPS();
      hasReceivedFrame.value = true;
      isPlaying.value = true;

      // 触发事件
      emit("frameReceived", img.width, img.height);

      // 清理URL对象
      URL.revokeObjectURL(imageUrl);
    };

    img.onerror = (error) => {
      console.error("❌ JPEG图像加载失败:", error);
      emit("error", "JPEG图像加载失败");
      URL.revokeObjectURL(imageUrl);
    };

    img.src = imageUrl;
  } catch (error) {
    console.error("❌ JPEG帧显示失败:", error);
    emit("error", "JPEG帧显示失败: " + (error as Error).message);
  }
};

// 控制方法
const togglePlay = () => {
  isPlaying.value = !isPlaying.value;
};

const saveCurrentFrame = () => {
  if (!canvasRef.value) return;

  try {
    canvasRef.value.toBlob((blob) => {
      if (blob) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `frame_${Date.now()}.png`;
        link.click();
        URL.revokeObjectURL(url);
      }
    }, "image/png");
  } catch (error) {
    console.error("❌ 保存帧失败:", error);
    emit("error", "保存帧失败");
  }
};

const toggleDetections = () => {
  // 触发父组件切换检测显示
};

const toggleVideoInfo = () => {
  showVideoInfo.value = !showVideoInfo.value;
};

// 清除画布
const clearCanvas = () => {
  if (canvasRef.value) {
    const ctx = canvasRef.value.getContext("2d");
    if (ctx) {
      ctx.clearRect(0, 0, canvasRef.value.width, canvasRef.value.height);
    }
  }
  hasReceivedFrame.value = false;
  isPlaying.value = false;
  frameCount.value = 0;
  fps.value = 0;
};

// 更新延迟（由父组件调用）
const updateLatency = (ms: number) => {
  latency.value = ms;
};

// 暴露方法给父组件
defineExpose({
  displayJpegFrame,
  updateDetections,
  updateLatency,
  clearCanvas,
  saveCurrentFrame,
});

// 生命周期
onMounted(() => {
  console.log("🎬 JPEG视频播放器已挂载");
});

onUnmounted(() => {
  // 清理资源
  clearCanvas();
});
</script>

<style scoped>
.jpeg-video-player {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.video-container {
  position: relative;
  background-color: #000;
  border-radius: 8px;
  overflow: hidden;
  border: 2px solid var(--el-border-color);
}

.video-canvas {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.video-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.status-indicator {
  position: absolute;
  top: 10px;
  left: 10px;
  pointer-events: auto;
}

.detections-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.detection-box {
  position: absolute;
  border: 2px solid #00ff00;
  background-color: rgba(0, 255, 0, 0.1);
  box-sizing: border-box;
}

.detection-label {
  position: absolute;
  top: -25px;
  left: 0;
  background-color: #00ff00;
  color: #000;
  padding: 2px 6px;
  font-size: 12px;
  border-radius: 3px;
  white-space: nowrap;
  font-weight: bold;
}

.video-info {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  pointer-events: auto;
}

.info-item {
  margin-bottom: 2px;
}

.info-item:last-child {
  margin-bottom: 0;
}

.no-video-placeholder {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #666;
  background:
    linear-gradient(45deg, #333 25%, transparent 25%),
    linear-gradient(-45deg, #333 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #333 75%),
    linear-gradient(-45deg, transparent 75%, #333 75%);
  background-size: 20px 20px;
  background-position:
    0 0,
    0 10px,
    10px -10px,
    -10px 0px;
}

.controls {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}
</style>
