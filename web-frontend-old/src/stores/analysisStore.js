import { defineStore } from "pinia";
import { computed, ref } from "vue";
const ANALYSIS_API_BASE = "/api/analyzer";
export const useAnalysisStore = defineStore("analysis", () => {
  // state
  const analysisResults = ref([]);
  const analysisTasks = ref([]);
  const availableModels = ref([]);
  const analysisSources = ref([]);
  const loading = ref(false);
  const error = ref(null);
  const selectedModelId = ref("");
  const selectedAnalysisType = ref("object_detection");
  // static options
  const analysisTypes = ref([
    { id: "object_detection", name: "Object Detection", enabled: true },
    {
      id: "instance_segmentation",
      name: "Instance Segmentation",
      enabled: false,
    },
  ]);
  // computed
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
      .slice()
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, 50),
  );
  // helpers
  const apiCall = async (endpoint, init = {}) => {
    loading.value = true;
    error.value = null;
    try {
      const response = await fetch(`${ANALYSIS_API_BASE}${endpoint}`, {
        headers: {
          "Content-Type": "application/json",
          ...init.headers,
        },
        ...init,
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.message || ` ${endpoint} ʧ`);
      }
      return payload.data;
    } catch (err) {
      error.value = err?.message ?? "ʧ";
      throw err;
    } finally {
      loading.value = false;
    }
  };
  // model management
  const fetchModels = async () => {
    try {
      const data = await apiCall("/models");
      availableModels.value = Array.isArray(data) ? data : [];
    } catch (err) {
      console.error("ȡģбʧ:", err);
    }
  };
  const loadModel = async (modelId) => {
    await apiCall("/models/load", {
      method: "POST",
      body: JSON.stringify({ model_id: modelId }),
    });
    const model = availableModels.value.find((m) => m.id === modelId);
    if (model) {
      model.status = "loaded";
    }
  };
  const unloadModel = async (modelId) => {
    await apiCall("/models/unload", {
      method: "POST",
      body: JSON.stringify({ model_id: modelId }),
    });
    const model = availableModels.value.find((m) => m.id === modelId);
    if (model) {
      model.status = "available";
    }
  };
  const getModelInfo = async (modelId) => {
    return apiCall(`/models/${modelId}`);
  };
  // task management
  const fetchAnalysisTasks = async () => {
    try {
      const tasks = await apiCall("/analysis/tasks");
      analysisTasks.value = Array.isArray(tasks) ? tasks : [];
      return analysisTasks.value;
    } catch (err) {
      console.error("ȡʧ:", err);
      throw err;
    }
  };
  const startAnalysis = async (sourceId, modelId, analysisType) => {
    const data = await apiCall("/analysis/start", {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId,
        model_id: modelId,
        analysis_type: analysisType,
      }),
    });
    analysisTasks.value.unshift(data);
    return data;
  };
  const stopAnalysis = async (taskId) => {
    await apiCall("/analysis/stop", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId }),
    });
    analysisTasks.value = analysisTasks.value.map((task) =>
      task.task_id === taskId ? { ...task, status: "stopped" } : task,
    );
  };
  const getAnalysisStatus = async (taskId) => {
    return apiCall(`/analysis/status?task_id=${encodeURIComponent(taskId)}`);
  };
  const fetchAnalysisResults = async (taskId, limit = 50) => {
    try {
      const params = new URLSearchParams();
      if (taskId) params.append("task_id", taskId);
      params.append("limit", String(limit));
      const query = params.toString();
      const results = await apiCall(
        `/analysis/results${query ? `?${query}` : ""}`,
      );
      if (Array.isArray(results)) {
        for (const result of results) {
          const key = `${result.source_id}-${result.request_id ?? result.timestamp}`;
          const exists = analysisResults.value.find(
            (existing) =>
              `${existing.source_id}-${existing.request_id ?? existing.timestamp}` ===
              key,
          );
          if (!exists) {
            analysisResults.value.unshift(result);
          }
        }
        if (analysisResults.value.length > 1000) {
          analysisResults.value = analysisResults.value.slice(0, 1000);
        }
      }
      return results;
    } catch (err) {
      console.error("ȡʧ:", err);
      throw err;
    }
  };
  // source management
  const fetchAnalysisSources = async () => {
    try {
      const sources = await apiCall("/sources");
      analysisSources.value = Array.isArray(sources) ? sources : [];
      return analysisSources.value;
    } catch (err) {
      console.error("ȡƵԴʧ:", err);
      throw err;
    }
  };
  const addAnalysisSource = async (sourceId, rtspUrl) => {
    const payload = await apiCall("/sources", {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId,
        rtsp_url: rtspUrl,
      }),
    });
    analysisSources.value.push(payload);
    return payload;
  };
  const removeAnalysisSource = async (sourceId) => {
    await apiCall(`/sources/${encodeURIComponent(sourceId)}`, {
      method: "DELETE",
    });
    analysisSources.value = analysisSources.value.filter(
      (source) => source.source_id !== sourceId,
    );
  };
  // system info
  const getSystemInfo = async () => apiCall("/system/info");
  const getPerformanceStats = async () => apiCall("/system/stats");
  // helpers
  const getTaskBySourceId = (sourceId) =>
    analysisTasks.value.find(
      (task) => task.source_id === sourceId && task.status === "running",
    );
  const getResultsBySourceId = (sourceId, limit = 10) =>
    analysisResults.value
      .filter((result) => result.source_id === sourceId)
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, limit);
  const startPeriodicRefresh = (interval = 5000) => {
    const timer = setInterval(async () => {
      try {
        await Promise.all([fetchAnalysisTasks(), fetchAnalysisResults()]);
      } catch (err) {
        console.error("ˢʧ:", err);
      }
    }, interval);
    return () => clearInterval(timer);
  };
  const init = async () => {
    await Promise.all([
      fetchModels(),
      fetchAnalysisTasks(),
      fetchAnalysisSources(),
      fetchAnalysisResults(),
    ]);
    if (availableModels.value.length > 0 && !selectedModelId.value) {
      selectedModelId.value = availableModels.value[0].id;
    }
  };
  return {
    // state
    analysisResults,
    analysisTasks,
    availableModels,
    analysisSources,
    analysisTypes,
    loading,
    error,
    selectedModelId,
    selectedAnalysisType,
    // computed
    runningTasks,
    loadedModels,
    activeAnalysisSources,
    recentAnalysisResults,
    // API operations
    fetchModels,
    loadModel,
    unloadModel,
    getModelInfo,
    fetchAnalysisTasks,
    startAnalysis,
    stopAnalysis,
    getAnalysisStatus,
    fetchAnalysisResults,
    fetchAnalysisSources,
    addAnalysisSource,
    removeAnalysisSource,
    getSystemInfo,
    getPerformanceStats,
    // helpers
    getTaskBySourceId,
    getResultsBySourceId,
    startPeriodicRefresh,
    init,
  };
});
