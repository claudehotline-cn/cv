<template>
  <div class="settings">
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <span>系统配置</span>
          </template>

          <el-form label-width="120px">
            <el-form-item label="视频帧率">
              <el-slider
                v-model="settings.defaultFps"
                :min="1"
                :max="60"
                :step="1"
                show-stops
                show-input
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="分析线程数">
              <el-input-number
                v-model="settings.workerThreads"
                :min="1"
                :max="8"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="检测阈值">
              <el-slider
                v-model="settings.confidenceThreshold"
                :min="0"
                :max="1"
                :step="0.01"
                :format-tooltip="formatPercentage"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="启用GPU加速">
              <el-switch v-model="settings.enableGPU" />
            </el-form-item>

            <el-form-item label="自动保存结果">
              <el-switch v-model="settings.autoSaveResults" />
            </el-form-item>

            <el-form-item label="结果保存路径">
              <el-input
                v-model="settings.resultsPath"
                placeholder="请输入保存路径"
                :disabled="!settings.autoSaveResults"
              >
                <template #append>
                  <el-button @click="selectFolder">浏览</el-button>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="saveSettings"
                >保存配置</el-button
              >
              <el-button @click="resetSettings">重置为默认</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <span>模型管理</span>
          </template>

          <el-table :data="modelList" size="small">
            <el-table-column prop="name" label="模型名称" width="150" />
            <el-table-column prop="type" label="类型" width="100">
              <template #default="{ row }">
                <el-tag
                  :type="row.type === 'detection' ? 'primary' : 'success'"
                  size="small"
                >
                  {{ row.type === "detection" ? "检测" : "分割" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag
                  :type="row.status === 'loaded' ? 'success' : 'info'"
                  size="small"
                >
                  {{ row.status === "loaded" ? "已加载" : "未加载" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button
                  size="small"
                  :type="row.status === 'loaded' ? 'warning' : 'primary'"
                  link
                  @click="toggleModel(row)"
                >
                  {{ row.status === "loaded" ? "卸载" : "加载" }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="margin-top: 20px">
            <el-upload
              class="upload-demo"
              drag
              action="/api/models/upload"
              :on-success="handleModelUpload"
              :before-upload="beforeModelUpload"
              accept=".onnx,.pt,.pth"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                将模型文件拖到此处，或<em>点击上传</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  支持 .onnx, .pt, .pth 格式的模型文件
                </div>
              </template>
            </el-upload>
          </div>
        </el-card>

        <el-card shadow="hover" style="margin-top: 20px">
          <template #header>
            <span>系统状态</span>
          </template>

          <el-descriptions :column="1" border>
            <el-descriptions-item label="系统版本">
              v1.0.0
            </el-descriptions-item>
            <el-descriptions-item label="运行时间">
              {{ systemUptime }}
            </el-descriptions-item>
            <el-descriptions-item label="CPU使用率">
              <el-progress
                :percentage="systemStats.cpuUsage"
                :stroke-width="8"
              />
            </el-descriptions-item>
            <el-descriptions-item label="内存使用率">
              <el-progress
                :percentage="systemStats.memoryUsage"
                :stroke-width="8"
              />
            </el-descriptions-item>
            <el-descriptions-item label="GPU使用率">
              <el-progress
                :percentage="systemStats.gpuUsage"
                :stroke-width="8"
                :status="systemStats.gpuUsage > 80 ? 'exception' : undefined"
              />
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { ElMessage } from "element-plus";

interface Settings {
  defaultFps: number;
  workerThreads: number;
  confidenceThreshold: number;
  enableGPU: boolean;
  autoSaveResults: boolean;
  resultsPath: string;
}

interface ModelInfo {
  id: string;
  name: string;
  type: "detection" | "segmentation";
  status: "loaded" | "unloaded";
  path: string;
  size: string;
}

interface SystemStats {
  cpuUsage: number;
  memoryUsage: number;
  gpuUsage: number;
}

// 数据
const settings = ref<Settings>({
  defaultFps: 30,
  workerThreads: 2,
  confidenceThreshold: 0.5,
  enableGPU: true,
  autoSaveResults: false,
  resultsPath: "./results",
});

const modelList = ref<ModelInfo[]>([
  {
    id: "1",
    name: "YOLOv5s",
    type: "detection",
    status: "loaded",
    path: "models/yolov5s.onnx",
    size: "14.1 MB",
  },
  {
    id: "2",
    name: "YOLOv5s-seg",
    type: "segmentation",
    status: "unloaded",
    path: "models/yolov5s-seg.onnx",
    size: "14.9 MB",
  },
]);

const systemStats = ref<SystemStats>({
  cpuUsage: 45,
  memoryUsage: 62,
  gpuUsage: 78,
});

const systemUptime = ref("12天 5小时 32分钟");
let statsTimer: number | null = null;

// 方法
const formatPercentage = (val: number) => {
  return `${Math.round(val * 100)}%`;
};

const selectFolder = () => {
  // 这里应该打开文件夹选择对话框
  ElMessage.info("文件夹选择功能需要结合后端API实现");
};

const saveSettings = () => {
  // 保存设置到后端
  ElMessage.success("设置已保存");

  // 这里应该发送设置到后端
  console.log("保存的设置:", settings.value);
};

const resetSettings = () => {
  settings.value = {
    defaultFps: 30,
    workerThreads: 2,
    confidenceThreshold: 0.5,
    enableGPU: true,
    autoSaveResults: false,
    resultsPath: "./results",
  };
  ElMessage.info("设置已重置为默认值");
};

const toggleModel = (model: ModelInfo) => {
  if (model.status === "loaded") {
    model.status = "unloaded";
    ElMessage.success(`模型 ${model.name} 已卸载`);
  } else {
    model.status = "loaded";
    ElMessage.success(`模型 ${model.name} 已加载`);
  }

  // 这里应该发送请求到后端加载/卸载模型
};

const beforeModelUpload = (file: File) => {
  const isValidFormat =
    file.name.endsWith(".onnx") ||
    file.name.endsWith(".pt") ||
    file.name.endsWith(".pth");

  if (!isValidFormat) {
    ElMessage.error("只支持 .onnx, .pt, .pth 格式的模型文件!");
    return false;
  }

  const isLt100M = file.size / 1024 / 1024 < 100;
  if (!isLt100M) {
    ElMessage.error("模型文件大小不能超过 100MB!");
    return false;
  }

  return true;
};

const handleModelUpload = (response: any, file: File) => {
  ElMessage.success(`模型 ${file.name} 上传成功`);

  // 添加到模型列表
  const newModel: ModelInfo = {
    id: Date.now().toString(),
    name: file.name.replace(/\.[^/.]+$/, ""),
    type: file.name.includes("seg") ? "segmentation" : "detection",
    status: "unloaded",
    path: response.path || `models/${file.name}`,
    size: `${(file.size / 1024 / 1024).toFixed(1)} MB`,
  };

  modelList.value.push(newModel);
};

const updateSystemStats = () => {
  // 模拟系统状态更新
  systemStats.value.cpuUsage = Math.round(Math.random() * 40 + 30);
  systemStats.value.memoryUsage = Math.round(Math.random() * 30 + 50);
  systemStats.value.gpuUsage = Math.round(Math.random() * 40 + 40);
};

const updateUptime = () => {
  // 这里应该从后端获取真实的运行时间
  // 现在只是模拟
};

// 生命周期
onMounted(() => {
  // 每5秒更新一次系统状态
  statsTimer = window.setInterval(() => {
    updateSystemStats();
    updateUptime();
  }, 5000);

  // 初始加载设置
  // loadSettingsFromBackend()
});

onUnmounted(() => {
  if (statsTimer) {
    clearInterval(statsTimer);
  }
});
</script>

<style scoped>
.settings {
  height: 100%;
}

.upload-demo {
  width: 100%;
}

:deep(.el-upload-dragger) {
  width: 100%;
}
</style>
