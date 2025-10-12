import { defineStore } from "pinia";
import { ref, computed } from "vue";
const VIDEO_SOURCE_API_BASE = "/api/source-manager";
export const useVideoSourceStore = defineStore("videoSource", () => {
  // 状态
  const videoSources = ref([]);
  const loading = ref(false);
  const error = ref(null);
  // 计算属性
  const activeVideoSources = computed(() =>
    videoSources.value.filter((source) => source.status === "active"),
  );
  // API调用方法
  const apiCall = async (endpoint, options = {}) => {
    loading.value = true;
    error.value = null;
    try {
      const response = await fetch(`${VIDEO_SOURCE_API_BASE}${endpoint}`, {
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
    } catch (err) {
      error.value = err.message;
      throw err;
    } finally {
      loading.value = false;
    }
  };
  // 获取所有视频源
  const fetchVideoSources = async () => {
    try {
      const data = await apiCall("/sources");
      videoSources.value = data || [];
    } catch (err) {
      console.error("获取视频源列表失败:", err);
    }
  };
  // 添加视频源
  const addVideoSource = async (source) => {
    try {
      const newSource = await apiCall("/sources", {
        method: "POST",
        body: JSON.stringify(source),
      });
      videoSources.value.push(newSource);
      return newSource;
    } catch (err) {
      console.error("添加视频源失败:", err);
      throw err;
    }
  };
  // 更新视频源
  const updateVideoSource = async (id, updates) => {
    try {
      const updatedSource = await apiCall(`/sources/${id}`, {
        method: "PUT",
        body: JSON.stringify(updates),
      });
      const index = videoSources.value.findIndex((s) => s.id === id);
      if (index > -1) {
        videoSources.value[index] = updatedSource;
      }
      return updatedSource;
    } catch (err) {
      console.error("更新视频源失败:", err);
      throw err;
    }
  };
  // 删除视频源
  const deleteVideoSource = async (id) => {
    try {
      await apiCall(`/sources/${id}`, {
        method: "DELETE",
      });
      const index = videoSources.value.findIndex((s) => s.id === id);
      if (index > -1) {
        videoSources.value.splice(index, 1);
      }
    } catch (err) {
      console.error("删除视频源失败:", err);
      throw err;
    }
  };
  // 获取视频源详细信息
  const getVideoSourceInfo = async (id) => {
    try {
      return await apiCall(`/sources/${id}`);
    } catch (err) {
      console.error("获取视频源信息失败:", err);
      throw err;
    }
  };
  // 启动RTSP推流
  const startRTSP = async (id) => {
    try {
      return await apiCall(`/sources/${id}/rtsp/start`, {
        method: "POST",
      });
    } catch (err) {
      console.error("启动RTSP推流失败:", err);
      throw err;
    }
  };
  // 停止RTSP推流
  const stopRTSP = async (id) => {
    try {
      return await apiCall(`/sources/${id}/rtsp/stop`, {
        method: "POST",
      });
    } catch (err) {
      console.error("停止RTSP推流失败:", err);
      throw err;
    }
  };
  // 获取RTSP状态
  const getRTSPStatus = async (id) => {
    try {
      return await apiCall(`/sources/${id}/rtsp/status`);
    } catch (err) {
      console.error("获取RTSP状态失败:", err);
      throw err;
    }
  };
  // 获取视频源统计信息
  const getVideoSourceStats = async (id) => {
    try {
      return await apiCall(`/sources/${id}/stats`);
    } catch (err) {
      console.error("获取视频源统计失败:", err);
      throw err;
    }
  };
  // 获取系统信息
  const getSystemInfo = async () => {
    try {
      return await apiCall("/system/info");
    } catch (err) {
      console.error("获取系统信息失败:", err);
      throw err;
    }
  };
  // 根据ID查找视频源
  const getVideoSourceById = (id) => {
    return videoSources.value.find((source) => source.id === id);
  };
  // 初始化
  const init = async () => {
    await fetchVideoSources();
  };
  return {
    // 状态
    videoSources,
    loading,
    error,
    // 计算属性
    activeVideoSources,
    // 方法
    fetchVideoSources,
    addVideoSource,
    updateVideoSource,
    deleteVideoSource,
    getVideoSourceInfo,
    startRTSP,
    stopRTSP,
    getRTSPStatus,
    getVideoSourceStats,
    getSystemInfo,
    getVideoSourceById,
    init,
  };
});
