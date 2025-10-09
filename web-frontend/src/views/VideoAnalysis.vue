<template>
  <div class="video-analysis">
    <el-row :gutter="20">
      <!-- 控制面板 -->
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>控制面板</span>
              <el-button size="small" type="primary" @click="goToSourceManager">
                管理视频源
              </el-button>
              </div>
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
              <div v-if="!videoStore.videoSources.length" class="no-sources-hint">
                <el-text type="info" size="small">暂无视频源，请先前往视频源管理页面添加</el-text>
              </div>
            </el-form-item>

            <el-form-item v-if="videoStore.selectedSource" label="当前源信息">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="名称">
                  {{ videoStore.selectedSource.name }}
                </el-descriptions-item>
                <el-descriptions-item label="类型">
                  <el-tag
                    :type="
                      videoStore.selectedSource.type === 'camera'
                        ? 'success'
                        : videoStore.selectedSource.type === 'file'
                          ? 'info'
                          : 'warning'
                    "
                    size="small"
                  >
                    {{ typeLabels[videoStore.selectedSource.type] }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag
                    :type="
                      videoStore.selectedSource.status === 'active'
                        ? 'success'
                        : videoStore.selectedSource.status === 'inactive'
                          ? 'info'
                          : 'danger'
                    "
                    size="small"
                  >
                    {{ statusLabels[videoStore.selectedSource.status] }}
                  </el-tag>
                </el-descriptions-item>
              </el-descriptions>
            </el-form-item>

            <el-form-item label="分析类型">
              <el-radio-group
                v-model="videoStore.selectedAnalysisType"
                @change="onAnalysisTypeChange"
              >
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

            <el-form-item label="选择模型">
              <el-select
                v-model="videoStore.selectedModelId"
                placeholder="请选择模型"
                style="width: 100%"
                @change="onModelChange"
              >
                <el-option
                  v-for="model in videoStore.filteredModels"
                  :key="model.id"
                  :label="model.name"
                  :value="model.id"
                />
              </el-select>
              <div v-if="!videoStore.filteredModels.length" class="no-models-hint">
                <el-text type="info" size="small">当前分析类型暂无可用模型</el-text>
              </div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="success"
                :disabled="videoStore.isAnalyzing"
                :loading="startingAnalysis"
                @click="startAnalysis"
              >
                开始分析
              </el-button>
              <el-button
                type="warning"
                :disabled="!videoStore.isAnalyzing"
                :loading="stoppingAnalysis"
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

      <!-- 视频预览区 -->
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
              <PlayerCard
                :title="selectedSourceName"
                :connected="videoStore.webrtcConnected"
                :connecting="videoStore.connectionStatus==='connecting'"
                :error="videoStore.connectionStatus==='disconnected' && !videoStore.webrtcConnected"
                :stats="{ fps: videoStore.selectedSource?.fps, resolution: videoStore.selectedSource?.resolution }"
                @play-pause="onPlayPause"
                @toggle-mute="onToggleMute"
                @screenshot="onScreenshot"
                @fullscreen="onFullscreen"
              >
              <video
                ref="videoElement"
                class="video-stream"
                autoplay
                muted
                playsinline
                :style="{ display: showVideo ? 'block' : 'none' }"
              ></video>
              <div class="webrtc-status">
                <el-tag :type="videoStore.webrtcConnected ? 'success' : 'danger'" size="small" effect="dark">
                  {{ videoStore.webrtcConnected ? 'WebRTC已连接' : 'WebRTC未连接' }}
                </el-tag>
              </div>
              <div class="video-controls">
                <el-button v-if="!videoStore.webrtcConnected" type="primary" size="small" @click="requestVideoStream">
                  <el-icon><CaretRight /></el-icon>
                  开始视频流
                </el-button>
                <el-button v-else type="warning" size="small" @click="stopVideoStream">
                  <el-icon><VideoPause /></el-icon>
                  停止视频流
                </el-button>
              </div>
              </PlayerCard>
            </div>
          </div>

          <!-- 最近结果 -->
          <div v-if="recentResult?.detections.length" style="margin-top: 20px">
            <el-divider content-position="left">最近检测</el-divider>
            <el-space wrap>
              <el-tag
                v-for="(detection, index) in recentResult.detections"
                :key="index"
                :type="getDetectionTagType(detection.confidence)"
                size="small"
              >
                {{ detection.class_name }}
                {{ Math.round(detection.confidence * 100) }}%
              </el-tag>
            </el-space>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
  
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import { useVideoStore } from "@/stores/videoStore";
import type { DetectionResult } from "@/types";
import { CaretRight, VideoPause, Camera } from "@element-plus/icons-vue";
import PlayerCard from "@/components/analysis/PlayerCard.vue";
import { ElMessage } from "element-plus";

const router = useRouter();
const videoStore = useVideoStore();

// 引用
const videoElement = ref<HTMLVideoElement | null>(null);

const startingAnalysis = ref(false);
const stoppingAnalysis = ref(false);

// 根据状态显示 video 标签
const showVideo = computed(() => {
  return videoStore.webrtcConnected || !!videoStore.videoStream;
});

// 标签映射
const typeLabels: Record<string, string> = {
  camera: "摄像头",
  file: "文件",
  stream: "流",
};

const statusLabels: Record<string, string> = {
  active: "运行中",
  inactive: "未运行",
  error: "错误",
};

// 计算属性
const selectedSourceName = computed(() => {
  return videoStore.selectedSource?.name || "未选择";
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

const getDetectionTagType = (confidence: number) => {
  if (confidence >= 0.8) return "success";
  if (confidence >= 0.6) return "warning";
  return "danger";
};

const goToSourceManager = () => {
  router.push("/video-source-manager");
};

// 模型/类型选择
const onAnalysisTypeChange = (analysisType: string) => {
  videoStore.setSelectedAnalysisType(analysisType);
};

const onModelChange = async (modelId: string) => {
  try {
    await videoStore.setSelectedModel(modelId);
  } catch (error) {
    console.error("切换模型失败:", error);
    ElMessage.error("切换模型失败");
  }
};

// WebRTC 方法
const requestVideoStream = async () => {
  if (!videoStore.webrtcConnected) {
    console.log("🔌 WebRTC未连接，先连接再请求视频...");
    await videoStore.connectWebRTC();
    setTimeout(() => {
      videoStore.requestVideoStream();
    }, 500);
  } else {
    videoStore.requestVideoStream();
  }
};

const stopVideoStream = () => {
  videoStore.disconnectWebRTC();
  if (videoElement.value) {
    videoElement.value.srcObject = null;
  }
  console.log("🛑 视频流已停止");
};
// PlayerCard 控件：仅作用于 <video> 标签，避免影响业务逻辑
const onPlayPause = () => {
  const v = videoElement.value; if (!v) return;
  if (v.paused) { v.play().catch(() => {}); } else { v.pause(); }
};
const onToggleMute = () => { const v = videoElement.value; if (!v) return; v.muted = !v.muted; };
const onFullscreen = () => {
  const v: any = videoElement.value; if (!v) return;
  (v.requestFullscreen || v.webkitRequestFullscreen || v.mozRequestFullScreen || v.msRequestFullscreen)?.call(v);
};
const onScreenshot = () => {
  const v = videoElement.value; if (!v) return;
  const canvas = document.createElement('canvas');
  canvas.width = v.videoWidth || 1280; canvas.height = v.videoHeight || 720;
  const ctx = canvas.getContext('2d'); if (!ctx) return; ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
  canvas.toBlob((blob) => { if (!blob) return; const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href=url; a.download='snapshot.png'; a.click(); URL.revokeObjectURL(url); }, 'image/png');
};

// 启停分析
const startAnalysis = async () => {
  startingAnalysis.value = true;
  try {
    await videoStore.startAnalysis(
      videoStore.selectedSourceId,
      videoStore.selectedAnalysisType,
    );
    console.log("✅ 开始分析成功");
  } catch (error) {
    console.error("❌ 开始分析失败:", error);
    ElMessage.error("开始分析失败: " + (error as Error).message);
  } finally {
    startingAnalysis.value = false;
  }
};

const stopAnalysis = async () => {
  stoppingAnalysis.value = true;
  try {
    await videoStore.stopAnalysis(videoStore.selectedSourceId);
    console.log("✅ 停止分析成功");
  } catch (error) {
    console.error("❌ 停止分析失败:", error);
    ElMessage.error("停止分析失败: " + (error as Error).message);
  } finally {
    stoppingAnalysis.value = false;
  }
};

// 源变化时自动处理
watch(
  () => videoStore.selectedSourceId,
  async (newSourceId, oldSourceId) => {
    if (newSourceId && newSourceId !== oldSourceId) {
      console.log("🎥 视频源切换:", oldSourceId, "->", newSourceId);
      if (videoStore.webrtcConnected) {
        setTimeout(() => {
          videoStore.requestVideoStream();
        }, 100);
      } else {
        await videoStore.connectWebRTC();
        setTimeout(() => {
          videoStore.requestVideoStream();
        }, 500);
      }
      await videoStore.getAnalysisStatus();
    }
  },
);

// 生命周期
onMounted(async () => {
  console.log("🎬 VideoAnalysis 组件已挂载");
  videoStore.init();

  setTimeout(async () => {
    console.log("🎥 准备设置视频元素");
    if (videoElement.value) {
      console.log("📹 找到视频元素，正在设置到store");
      videoStore.setVideoElement(videoElement.value);
    }

    // 自动开启分析
    if (videoStore.selectedSourceId) {
      try {
        await videoStore.startAnalysis(
          videoStore.selectedSourceId,
          videoStore.selectedAnalysisType,
        );
      } catch (error) {
        console.error("自动启动分析失败:", error);
      }
    }

    // 不在此处自动请求视频流，避免与 onConnected 重复触发
  }, 500);
});

onUnmounted(() => {
  videoStore.disconnectWebRTC();
  startingAnalysis.value = false;
  stoppingAnalysis.value = false;
});
</script>

<style scoped>
.video-analysis {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.no-sources-hint {
  margin-top: 8px;
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

.model-option {
  padding: 4px 0;
}

.model-name {
  font-weight: 500;
  margin-bottom: 4px;
}

.model-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-desc {
  font-size: 12px;
  color: #666;
  flex: 1;
}

.no-models-hint {
  margin-top: 8px;
}
</style>






