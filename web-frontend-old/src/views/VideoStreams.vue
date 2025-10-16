<template>
  <div class="video-streams">
    <el-row :gutter="20">
      <!-- 视频源管理面板 -->
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>视频源管理</span>
              <el-button
                size="small"
                type="primary"
                @click="addSourceDialogVisible = true"
              >
                添加视频源
              </el-button>
            </div>
          </template>

          <el-table
            :data="videoStore.videoSources"
            size="small"
            max-height="400"
          >
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="type" label="类型" width="80">
              <template #default="{ row }">
                <el-tag
                  :type="
                    row.type === 'camera'
                      ? 'success'
                      : row.type === 'file'
                        ? 'info'
                        : 'warning'
                  "
                  size="small"
                >
                  {{ getTypeLabel(row.type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag
                  :type="
                    row.status === 'active'
                      ? 'success'
                      : row.status === 'inactive'
                        ? 'info'
                        : 'danger'
                  "
                  size="small"
                >
                  {{ getStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  link
                  @click="selectSource(row.id)"
                >
                  选择
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  link
                  @click="removeSource(row.id)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 分析控制面板 -->
        <el-card shadow="hover" style="margin-top: 20px">
          <template #header>
            <span>分析控制</span>
          </template>

          <el-form label-width="100px">
            <el-form-item label="选择视频源">
              <el-select
                v-model="videoStore.selectedSourceId"
                placeholder="请选择视频源"
                style="width: 100%"
              >
                <el-option
                  v-for="source in videoStore.videoSources"
                  :key="source.id"
                  :label="source.name"
                  :value="source.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="分析类型">
              <el-radio-group v-model="videoStore.selectedAnalysisType">
                <el-radio
                  v-for="type in videoStore.analysisTypes"
                  :key="type.id"
                  :value="type.id"
                  :disabled="!type.enabled"
                >
                  {{ type.name }}
                </el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item>
              <el-button
                type="success"
                :disabled="!videoStore.selectedSourceId"
                @click="startAnalysis"
              >
                开始分析
              </el-button>
              <el-button
                type="warning"
                :disabled="!videoStore.selectedSourceId"
                @click="stopAnalysis"
              >
                停止分析
              </el-button>
            </el-form-item>
          </el-form>

          <div class="connection-status">
            <el-alert
              :type="connectionStatusType"
              :title="connectionStatusText"
              :closable="false"
              size="small"
            />
          </div>
        </el-card>
      </el-col>

      <!-- 视频预览面板 -->
      <el-col :span="16">
        <el-card shadow="hover">
          <template #header>
            <span>视频预览 - {{ selectedSourceName }}</span>
          </template>

          <div class="video-container">
            <div v-if="!videoStore.selectedSourceId" class="no-video">
              <el-icon size="80"><Camera /></el-icon>
              <p>请选择一个视频源</p>
            </div>
            <div v-else class="video-preview">
              <!-- JPEG视频播放器 -->
              <JpegVideoPlayer v-if="!videoStore.webrtcConnected"
                ref="jpegPlayerRef"
                :width="640"
                :height="480"
                :show-controls="true"
                :show-detections="false"
                :detections="recentResult?.detections || []"
                @frame-received="onFrameReceived"
                @error="onVideoError"
              />

              <!-- 备用: WebRTC视频流 (当不使用JPEG时) -->
              <video v-show="videoStore.webrtcConnected"
                ref="videoElement"
                class="video-stream"
                autoplay
                muted
                playsinline
              ></video>

              <!-- WebRTC连接状态指示器 -->
              <div class="webrtc-status">
                <el-tag
                  :type="videoStore.webrtcConnected ? 'success' : 'danger'"
                  size="small"
                  effect="dark"
                >
                  {{
                    videoStore.webrtcConnected ? "WebRTC已连接" : "WebRTC未连接"
                  }}
                </el-tag>
              </div>

              <!-- 分析结果叠加层 -->
              <div v-if="false" class="analysis-overlay">
                <div
                  v-for="detection in recentResult.detections"
                  :key="`${detection.bbox.x}-${detection.bbox.y}`"
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

              <!-- 视频流控制按钮 -->
              <div class="video-controls">
                <el-button
                  v-if="!videoStore.videoStream"
                  type="primary"
                  size="small"
                  @click="requestVideoStream"
                >
                  <el-icon><CaretRight /></el-icon>
                  开始视频流
                </el-button>
                <el-button
                  v-else
                  type="warning"
                  size="small"
                  @click="stopVideoStream"
                >
                  <el-icon><VideoPause /></el-icon>
                  停止视频流
                </el-button>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 分析结果统计 -->
        <el-card shadow="hover" style="margin-top: 20px">
          <template #header>
            <span>实时统计</span>
          </template>

          <el-row :gutter="20">
            <el-col :span="6">
              <el-statistic title="检测对象数" :value="currentDetectionCount" />
            </el-col>
            <el-col :span="6">
              <el-statistic title="分析帧数" :value="analysisFrameCount" />
            </el-col>
            <el-col :span="6">
              <el-statistic
                title="平均置信度"
                :value="averageConfidence"
                suffix="%"
              />
            </el-col>
            <el-col :span="6">
              <el-statistic
                title="处理延迟"
                :value="processingDelay"
                suffix="ms"
              />
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

    <!-- 添加视频源对话框 -->
    <el-dialog
      v-model="addSourceDialogVisible"
      title="添加视频源"
      width="500px"
    >
      <el-form :model="newSource" label-width="100px">
        <el-form-item label="源名称">
          <el-input v-model="newSource.name" placeholder="请输入源名称" />
        </el-form-item>
        <el-form-item label="源类型">
          <el-select
            v-model="newSource.type"
            placeholder="请选择类型"
            style="width: 100%"
          >
            <el-option label="摄像头" value="camera" />
            <el-option label="视频文件" value="file" />
            <el-option label="网络流" value="stream" />
          </el-select>
        </el-form-item>
        <el-form-item label="源地址">
          <el-input v-model="newSource.url" placeholder="请输入地址" />
        </el-form-item>
        <el-form-item label="帧率">
          <el-input-number v-model="newSource.fps" :min="1" :max="60" />
        </el-form-item>
        <el-form-item label="分辨率">
          <el-input v-model="newSource.resolution" placeholder="如: 1280x720" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="addSourceDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="addVideoSource">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useVideoStore } from "@/stores/videoStore";
import type { DetectionResult, VideoSource } from "@/types";
import { CaretRight, VideoPause, Camera } from "@element-plus/icons-vue";
import JpegVideoPlayer from "@/components/JpegVideoPlayer.vue";

const videoStore = useVideoStore();

// 数据
const addSourceDialogVisible = ref(false);
const videoElement = ref<HTMLVideoElement | null>(null);
const jpegPlayerRef = ref<InstanceType<typeof JpegVideoPlayer> | null>(null);
const newSource = ref({
  name: "",
  type: "camera" as const,
  url: "",
  fps: 30,
  resolution: "1280x720",
});

// 标签映射
type VideoSourceType = VideoSource["type"];
type VideoSourceStatus = VideoSource["status"];

const typeLabels: Record<VideoSourceType, string> = {
  camera: "\u6444\u50cf\u5934",
  file: "\u6587\u4ef6",
  stream: "\u6d41",
};

const statusLabels: Record<VideoSourceStatus, string> = {
  active: "\u5df2\u542f\u7528",
  inactive: "\u672a\u542f\u7528",
  error: "\u5f02\u5e38",
};

const getTypeLabel = (type: VideoSourceType) => typeLabels[type];
const getStatusLabel = (status: VideoSourceStatus) => statusLabels[status];

const selectedSourceName = computed(() => {
  return videoStore.selectedSource?.name || "未选择";
});

const selectedSourceType = computed(() => {
  const source = videoStore.selectedSource;
  return source ? getTypeLabel(source.type) : "";
});

const connectionStatusType = computed(() => {
  switch (videoStore.connectionStatus) {
    case "connected":
      return "success";
    case "connecting":
      return "warning";
    default:
      return "error";
  }
});

const connectionStatusText = computed(() => {
  switch (videoStore.connectionStatus) {
    case "connected":
      return "已连接到后端服务";
    case "connecting":
      return "正在连接后端服务...";
    default:
      return "后端服务连接失败";
  }
});

const recentResult = computed(() => {
  return videoStore.recentAnalysisResults[0];
});

const currentDetectionCount = computed(() => {
  return recentResult.value?.detections.length || 0;
});

const analysisFrameCount = computed(() => {
  return videoStore.analysisResults.length;
});

const averageConfidence = computed(() => {
  if (!recentResult.value?.detections.length) return 0;
  const sum = recentResult.value.detections.reduce(
    (acc, det) => acc + det.confidence,
    0,
  );
  return Math.round((sum / recentResult.value.detections.length) * 100);
});

const processingDelay = computed(() => {
  // 模拟处理延迟
  return Math.round(Math.random() * 100 + 50);
});

// 方法
const selectSource = (sourceId: string) => {
  videoStore.setSelectedSource(sourceId);
};

const removeSource = (sourceId: string) => {
  videoStore.removeVideoSource(sourceId);
};

const addVideoSource = () => {
  videoStore.addVideoSource(newSource.value);
  addSourceDialogVisible.value = false;
  newSource.value = {
    name: "",
    type: "camera",
    url: "",
    fps: 30,
    resolution: "1280x720",
  };
};

const startAnalysis = () => {
  videoStore.startAnalysis(
    videoStore.selectedSourceId,
    videoStore.selectedAnalysisType,
  );
};

const stopAnalysis = () => {
  videoStore.stopAnalysis(videoStore.selectedSourceId);
};

const getDetectionBoxStyle = (detection: DetectionResult) => {
  return {
    left: `${detection.bbox.x}px`,
    top: `${detection.bbox.y}px`,
    width: `${detection.bbox.width}px`,
    height: `${detection.bbox.height}px`,
  };
};

// WebRTC相关方法
const requestVideoStream = () => {
  videoStore.requestVideoStream();
};

const stopVideoStream = () => {
  // 停止当前视频流
  if (videoElement.value) {
    videoElement.value.srcObject = null;
  }
  // 清理JPEG播放器
  if (jpegPlayerRef.value) {
    jpegPlayerRef.value.clearCanvas();
  }
  // 这里可以发送停止信号给后端
  videoStore.stopAnalysis(videoStore.selectedSourceId);
};

// JPEG播放器事件处理
const onFrameReceived = (width: number, height: number) => {
  console.log("📹 接收到JPEG帧:", width, "x", height);
};

const onVideoError = (message: string) => {
  console.error("❌ JPEG播放器错误:", message);
};

// 生命周期
onMounted(async () => {
  console.log("🎬 VideoStreams组件已挂载");
  videoStore.init();

  // 等待WebRTC连接建立和DOM更新
  setTimeout(() => {
    console.log("🎥 准备设置视频元素和JPEG播放器");

    // 设置JPEG视频播放器
    if (jpegPlayerRef.value) {
      console.log("📹 找到JPEG播放器，正在设置到store");
      videoStore.setJpegVideoPlayer(jpegPlayerRef.value);
    } else {
      console.error("❌ JPEG播放器未找到");
    }

    // 设置备用视频元素
    if (videoElement.value) {
      console.log("📹 找到视频元素，正在设置到store");
      videoStore.setVideoElement(videoElement.value);
    }

    // 自动请求视频流（如果已选择源）
    if (videoStore.selectedSourceId) {
      console.log("🎬 自动请求视频流, sourceId:", videoStore.selectedSourceId);
      setTimeout(() => {
        videoStore.requestVideoStream();
      }, 500);
    }
  }, 1000); // 增加延迟确保WebRTC客户端已初始化
});

onUnmounted(() => {
  // 清理WebRTC连接
  videoStore.disconnectWebRTC();
});
</script>

<style scoped>
.video-streams {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.video-container {
  height: 400px;
  background-color: #000;
  border-radius: 8px;
  position: relative;
  overflow: hidden;
}

.no-video {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #666;
}

.video-preview {
  width: 100%;
  height: 100%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-stream {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background-color: #000;
  border-radius: 8px;
}

.video-placeholder {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: #999;
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
  border-radius: 8px;
  z-index: 1;
}

.webrtc-status {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
}

.video-controls {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
}

.analysis-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.detection-box {
  position: absolute;
  border: 2px solid #00ff00;
  background-color: rgba(0, 255, 0, 0.1);
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
}

.connection-status {
  margin-top: 20px;
}
</style>


