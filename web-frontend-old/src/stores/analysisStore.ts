import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { AnalysisResult, AnalysisType } from "@/types";

const ANALYSIS_API_BASE = "/api/analyzer";

interface AnalysisTask {
  task_id: string;
  source_id: string;
  model_id: string;
  analysis_type: string;
  status: "running" | "stopped" | "error";
  start_time: number;
  frames_processed: number;
  avg_fps: number;
}

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  status: "loaded" | "available" | "loading" | "error";
  format: string;
  accuracy?: number;
  inference_time_ms?: number;
}

interface AnalysisSource {
  source_id: string;
  rtsp_url: string;
  status: "active" | "inactive";
  analysis_enabled: boolean;
  fps: number;
  resolution: string;
}

export const useAnalysisStore = defineStore("analysis", () => {
  // 状态
  const analysisResults = ref<AnalysisResult[]>([]);
  const analysisTasks = ref<AnalysisTask[]>([]);
  const availableModels = ref<ModelInfo[]>([]);
  const analysisSources = ref<AnalysisSource[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const selectedModelId = ref<string>("");
  const selectedAnalysisType = ref<string>("object_detection");

  // 分析类型定义
  const analysisTypes = ref<AnalysisType[]>([
    { id: "object_detection", name: "目标检测", enabled: true },
    { id: "instance_segmentation", name: "实例分割", enabled: false },
  ]);

  // 计算属性
  const runningTasks = computed(() =>
    analysisTasks.value.filter((task) => task.status === "running"),
  );

  const loadedModels = computed(() =>
    availableModels.value.filter((model) => model.status === "loaded"),
  );

  const activeAnalysisSources = computed(() =>
    analysisSources.value.filter((source) => source.status === "active"),
  );

  const recentAnalysisResults = computed(() =>
    analysisResults.value
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, 50),
  );

  // API调用方法
  const apiCall = async (endpoint: string, options: RequestInit = {}) => {
    loading.value = true;
    error.value = null;

    try {
      const response = await fetch(`${ANALYSIS_API_BASE}${endpoint}`, {
        headers: {
          "Content-Type": "application/json",
          ...options.headers,
        },
        ...options,
      });

      const data = await response.json();

      if (!data.success) {
        throw new Error(data.message || "请求失败");
      }

      return data.data;
    } catch (err: any) {
      error.value = err.message;
      throw err;
    } finally {
      loading.value = false;
    }
  };

  // 模型管理
  const fetchModels = async () => {
    try {
      const data = await apiCall("/models");
      availableModels.value = data || [];
    } catch (err) {
      console.error("获取模型列表失败:", err);
    }
  };

  const loadModel = async (modelId: string) => {
    try {
      await apiCall("/models/load", {
        method: "POST",
        body: JSON.stringify({ model_id: modelId }),
      });

      // 更新模型状态
      const model = availableModels.value.find((m) => m.id === modelId);
      if (model) {
        model.status = "loaded";
      }

      return true;
    } catch (err) {
      console.error("加载模型失败:", err);
      throw err;
    }
  };

  const unloadModel = async (modelId: string) => {
    try {
      await apiCall("/models/unload", {
        method: "POST",
        body: JSON.stringify({ model_id: modelId }),
      });

      // 更新模型状态
      const model = availableModels.value.find((m) => m.id === modelId);
      if (model) {
        model.status = "available";
      }

      return true;
    } catch (err) {
      console.error("卸载模型失败:", err);
      throw err;
    }
  };

  const getModelInfo = async (modelId: string) => {
    try {
      return await apiCall(`/models/${modelId}`);
    } catch (err) {
      console.error("获取模型信息失败:", err);
      throw err;
    }
  };

  // 分析任务管理
  const fetchAnalysisTasks = async () => {
    try {
      const data = await apiCall("/analysis/tasks");
      analysisTasks.value = data || [];
    } catch (err) {
      console.error("获取分析任务失败:", err);
    }
  };

  const startAnalysis = async (
    sourceId: string,
    modelId: string,
    analysisType: string = "object_detection",
  ) => {
    try {
      const result = await apiCall("/analysis/start", {
        method: "POST",
        body: JSON.stringify({
          source_id: sourceId,
          model_id: modelId,
          analysis_type: analysisType,
        }),
      });

      // 添加到任务列表
      analysisTasks.value.push(result);

      return result;
    } catch (err) {
      console.error("启动分析失败:", err);
      throw err;
    }
  };

  const stopAnalysis = async (taskId: string) => {
    try {
      await apiCall("/analysis/stop", {
        method: "POST",
        body: JSON.stringify({ task_id: taskId }),
      });

      // 更新任务状态
      const task = analysisTasks.value.find((t) => t.task_id === taskId);
      if (task) {
        task.status = "stopped";
      }

      return true;
    } catch (err) {
      console.error("停止分析失败:", err);
      throw err;
    }
  };

  const getAnalysisStatus = async () => {
    try {
      return await apiCall("/analysis/status");
    } catch (err) {
      console.error("获取分析状态失败:", err);
      throw err;
    }
  };

  const fetchAnalysisResults = async (taskId?: string, limit: number = 50) => {
    try {
      const params = new URLSearchParams();
      if (taskId) params.append("task_id", taskId);
      params.append("limit", limit.toString());

      const queryString = params.toString() ? `?${params.toString()}` : "";
      const data = await apiCall(`/analysis/results${queryString}`);

      // 添加到结果列表，避免重复
      if (Array.isArray(data)) {
        data.forEach((result: AnalysisResult) => {
          const exists = analysisResults.value.find(
            (r) =>
              r.request_id === result.request_id &&
              r.timestamp === result.timestamp,
          );
          if (!exists) {
            analysisResults.value.unshift(result);
          }
        });

        // 保持最多1000个结果
        if (analysisResults.value.length > 1000) {
          analysisResults.value = analysisResults.value.slice(0, 1000);
        }
      }

      return data;
    } catch (err) {
      console.error("获取分析结果失败:", err);
      throw err;
    }
  };

  // 分析视频源管理
  const fetchAnalysisSources = async () => {
    try {
      const data = await apiCall("/sources");
      analysisSources.value = data || [];
    } catch (err) {
      console.error("获取分析视频源失败:", err);
    }
  };

  const addAnalysisSource = async (sourceId: string, rtspUrl: string) => {
    try {
      const result = await apiCall("/sources", {
        method: "POST",
        body: JSON.stringify({
          source_id: sourceId,
          rtsp_url: rtspUrl,
        }),
      });

      // 添加到分析源列表
      analysisSources.value.push(result);

      return result;
    } catch (err) {
      console.error("添加分析视频源失败:", err);
      throw err;
    }
  };

  const removeAnalysisSource = async (sourceId: string) => {
    try {
      await apiCall(`/sources/${sourceId}`, {
        method: "DELETE",
      });

      // 从列表中移除
      const index = analysisSources.value.findIndex(
        (s) => s.source_id === sourceId,
      );
      if (index > -1) {
        analysisSources.value.splice(index, 1);
      }

      return true;
    } catch (err) {
      console.error("移除分析视频源失败:", err);
      throw err;
    }
  };

  // 系统信息和统计
  const getSystemInfo = async () => {
    try {
      return await apiCall("/system/info");
    } catch (err) {
      console.error("获取系统信息失败:", err);
      throw err;
    }
  };

  const getPerformanceStats = async () => {
    try {
      return await apiCall("/system/stats");
    } catch (err) {
      console.error("获取性能统计失败:", err);
      throw err;
    }
  };

  // 工具方法
  const getTaskBySourceId = (sourceId: string) => {
    return analysisTasks.value.find(
      (task) => task.source_id === sourceId && task.status === "running",
    );
  };

  const getResultsBySourceId = (sourceId: string, limit: number = 10) => {
    return analysisResults.value
      .filter((result) => result.source_id === sourceId)
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, limit);
  };

  // 定期刷新数据
  const startPeriodicRefresh = (interval: number = 5000) => {
    const timer = setInterval(async () => {
      try {
        await Promise.all([fetchAnalysisTasks(), fetchAnalysisResults()]);
      } catch (err) {
        console.error("定期刷新数据失败:", err);
      }
    }, interval);

    return () => clearInterval(timer);
  };

  // 初始化
  const init = async () => {
    await Promise.all([
      fetchModels(),
      fetchAnalysisTasks(),
      fetchAnalysisSources(),
      fetchAnalysisResults(),
    ]);

    // 设置默认选择的模型
    if (availableModels.value.length > 0 && !selectedModelId.value) {
      selectedModelId.value = availableModels.value[0].id;
    }
  };

  return {
    // 状态
    analysisResults,
    analysisTasks,
    availableModels,
    analysisSources,
    analysisTypes,
    loading,
    error,
    selectedModelId,
    selectedAnalysisType,

    // 计算属性
    runningTasks,
    loadedModels,
    activeAnalysisSources,
    recentAnalysisResults,

    // 模型管理
    fetchModels,
    loadModel,
    unloadModel,
    getModelInfo,

    // 分析任务管理
    fetchAnalysisTasks,
    startAnalysis,
    stopAnalysis,
    getAnalysisStatus,
    fetchAnalysisResults,

    // 分析视频源管理
    fetchAnalysisSources,
    addAnalysisSource,
    removeAnalysisSource,

    // 系统信息
    getSystemInfo,
    getPerformanceStats,

    // 工具方法
    getTaskBySourceId,
    getResultsBySourceId,
    startPeriodicRefresh,

    init,
  };
});
