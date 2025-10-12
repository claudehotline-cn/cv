<template>
  <div class="video-analysis-control">
    <el-card class="control-panel">
      <template #header>
        <div class="card-header">
          <span>视频分析控制面板</span>
          <el-button
            type="primary"
            size="small"
            :loading="appStore.globalLoading"
            @click="refreshData"
          >
            刷新数据
          </el-button>
        </div>
      </template>

      <!-- 视频源选择 -->
      <div class="section">
        <h3>视频源选择</h3>
        <el-select
          v-model="appStore.selectedSourceId"
          placeholder="选择视频源"
          style="width: 100%"
          @change="handleSourceChange"
        >
          <el-option
            v-for="source in videoSourceStore.activeVideoSources"
            :key="source.id"
            :label="source.name"
            :value="source.id"
          >
            <span>{{ source.name }}</span>
            <span style="float: right; color: var(--el-text-color-secondary)">
              {{ source.resolution }} - {{ source.fps }}fps
            </span>
          </el-option>
        </el-select>
      </div>

      <!-- 模型选择 -->
      <div class="section">
        <h3>AI模型选择</h3>
        <el-select
          v-model="analysisStore.selectedModelId"
          placeholder="选择AI模型"
          style="width: 100%"
        >
          <el-option
            v-for="model in analysisStore.availableModels"
            :key="model.id"
            :label="model.name"
            :value="model.id"
          >
            <span>{{ model.name }}</span>
            <el-tag
              :type="model.status === 'loaded' ? 'success' : 'info'"
              size="small"
              style="float: right"
            >
              {{ model.status === "loaded" ? "已加载" : "可用" }}
            </el-tag>
          </el-option>
        </el-select>
      </div>

      <!-- 分析类型 -->
      <div class="section">
        <h3>分析类型</h3>
        <el-radio-group v-model="analysisStore.selectedAnalysisType">
          <el-radio
            v-for="type in analysisStore.analysisTypes"
            :key="type.id"
            :label="type.id"
            :disabled="!type.enabled"
          >
            {{ type.name }}
          </el-radio>
        </el-radio-group>
      </div>

      <!-- 控制按钮 -->
      <div class="section actions">
        <el-button
          v-if="!appStore.isAnalysisRunning"
          type="primary"
          size="large"
          :disabled="!canStartAnalysis"
          :loading="appStore.globalLoading"
          @click="startAnalysis"
        >
          开始分析
        </el-button>
        <el-button
          v-else
          type="danger"
          size="large"
          :loading="appStore.globalLoading"
          @click="stopAnalysis"
        >
          停止分析
        </el-button>
      </div>

      <!-- 状态显示 -->
      <div v-if="appStore.selectedSourceTask" class="section status">
        <h3>分析状态</h3>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务ID">
            {{ appStore.selectedSourceTask.task_id }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag
              :type="getStatusTagType(appStore.selectedSourceTask.status)"
            >
              {{ getStatusText(appStore.selectedSourceTask.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="已处理帧数">
            {{ appStore.selectedSourceTask.frames_processed }}
          </el-descriptions-item>
          <el-descriptions-item label="平均FPS">
            {{ appStore.selectedSourceTask.avg_fps.toFixed(1) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-card>

    <!-- 分析结果 -->
    <el-card
      v-if="appStore.selectedSourceResults.length > 0"
      class="results-panel"
    >
      <template #header>
        <span>最新分析结果</span>
      </template>

      <div class="results-list">
        <div
          v-for="result in appStore.selectedSourceResults"
          :key="`${result.request_id}-${result.timestamp}`"
          class="result-item"
        >
          <div class="result-header">
            <span class="timestamp">
              {{ formatTimestamp(result.timestamp) }}
            </span>
            <span class="frame-id"> 帧 #{{ result.request_id }} </span>
          </div>
          <div
            v-if="result.detections && result.detections.length > 0"
            class="detections"
          >
            <el-tag
              v-for="(detection, index) in result.detections"
              :key="index"
              class="detection-tag"
              size="small"
            >
              {{ detection.class_name }} ({{
                (detection.confidence * 100).toFixed(1)
              }}%)
            </el-tag>
          </div>
          <div v-else class="no-detections">无检测结果</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";
import { useAppStore } from "@/stores/appStore";
import { ElMessage } from "element-plus";

const appStore = useAppStore();
const videoSourceStore = appStore.videoSourceStore;
const analysisStore = appStore.analysisStore;

// 监听模型选择变化，自动切换模型
watch(
  () => analysisStore.selectedModelId,
  async (newModelId, oldModelId) => {
    if (newModelId && newModelId !== oldModelId && oldModelId !== "") {
      try {
        await analysisStore.loadModel(newModelId);
        ElMessage.success(`已切换到模型: ${newModelId}`);
      } catch (error: any) {
        ElMessage.error(`模型切换失败: ${error.message}`);
      }
    }
  },
);

// 计算属性
const canStartAnalysis = computed(
  () =>
    appStore.selectedSourceId &&
    analysisStore.selectedModelId &&
    !appStore.globalLoading,
);

// 方法
const handleSourceChange = (sourceId: string) => {
  appStore.setSelectedSource(sourceId);
};

const refreshData = async () => {
  try {
    await appStore.refreshAllData();
    ElMessage.success("数据刷新成功");
  } catch (error) {
    ElMessage.error("数据刷新失败");
  }
};

const startAnalysis = async () => {
  if (!appStore.selectedSourceId || !analysisStore.selectedModelId) {
    ElMessage.warning("请先选择视频源和AI模型");
    return;
  }

  try {
    await appStore.startFullAnalysisWorkflow(
      appStore.selectedSourceId,
      analysisStore.selectedModelId,
      analysisStore.selectedAnalysisType,
    );
    ElMessage.success("分析任务启动成功");
  } catch (error: any) {
    ElMessage.error(`启动分析失败: ${error.message}`);
  }
};

const stopAnalysis = async () => {
  if (!appStore.selectedSourceId) {
    return;
  }

  try {
    await appStore.stopFullAnalysisWorkflow(appStore.selectedSourceId);
    ElMessage.success("分析任务已停止");
  } catch (error: any) {
    ElMessage.error(`停止分析失败: ${error.message}`);
  }
};

const getStatusTagType = (status: string) => {
  switch (status) {
    case "running":
      return "success";
    case "stopped":
      return "info";
    case "error":
      return "danger";
    default:
      return "info";
  }
};

const getStatusText = (status: string) => {
  switch (status) {
    case "running":
      return "运行中";
    case "stopped":
      return "已停止";
    case "error":
      return "错误";
    default:
      return "未知";
  }
};

const formatTimestamp = (timestamp: number) => {
  return new Date(timestamp * 1000).toLocaleTimeString();
};

// 初始化
appStore.init();
</script>

<style scoped>
.video-analysis-control {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section {
  margin-bottom: 20px;
}

.section h3 {
  margin-bottom: 10px;
  color: var(--el-text-color-primary);
}

.actions {
  text-align: center;
}

.status .el-descriptions {
  margin-top: 10px;
}

.results-panel {
  max-height: 400px;
  overflow-y: auto;
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.result-item {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 10px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.timestamp {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.frame-id {
  color: var(--el-text-color-regular);
  font-size: 12px;
}

.detections {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.detection-tag {
  margin-right: 5px;
}

.no-detections {
  color: var(--el-text-color-secondary);
  font-style: italic;
}
</style>
