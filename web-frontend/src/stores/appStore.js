import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useVideoSourceStore } from "./videoSourceStore";
import { useAnalysisStore } from "./analysisStore";
import { WebRTCClient } from "@/utils/webrtc";
export const useAppStore = defineStore("app", () => {
  // 子store实例
  const videoSourceStore = useVideoSourceStore();
  const analysisStore = useAnalysisStore();
  // 应用级状态
  const selectedSourceId = ref("");
  const isInitialized = ref(false);
  const globalLoading = ref(false);
  // WebRTC相关状态
  const webrtcClient = ref(null);
  const webrtcConnected = ref(false);
  const videoStream = ref(null);
  const currentVideoElement = ref(null);
  // 计算属性
  const selectedSource = computed(() =>
    videoSourceStore.getVideoSourceById(selectedSourceId.value),
  );
  const selectedSourceTask = computed(() =>
    analysisStore.getTaskBySourceId(selectedSourceId.value),
  );
  const selectedSourceResults = computed(() =>
    analysisStore.getResultsBySourceId(selectedSourceId.value, 10),
  );
  const isAnalysisRunning = computed(
    () =>
      !!selectedSourceTask.value &&
      selectedSourceTask.value.status === "running",
  );
  // WebRTC相关方法
  const initWebRTC = () => {
    const config = {
      signalingServerUrl: "ws://127.0.0.1:8083",
      stunServers: [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
      ],
    };
    webrtcClient.value = new WebRTCClient(config);
    webrtcClient.value.setEventHandlers({
      onConnected: () => {
        webrtcConnected.value = true;
        console.log("WebRTC连接建立");
      },
      onDisconnected: () => {
        webrtcConnected.value = false;
        videoStream.value = null;
        console.log("WebRTC连接断开");
      },
      onVideoStream: (stream) => {
        videoStream.value = stream;
        if (currentVideoElement.value) {
          currentVideoElement.value.srcObject = stream;
        }
        console.log("接收到视频流");
      },
      onError: (error) => {
        console.error("WebRTC错误:", error);
      },
    });
  };
  const connectWebRTC = async () => {
    if (!webrtcClient.value) {
      initWebRTC();
    }
    try {
      const success = await webrtcClient.value?.connect();
      if (success) {
        console.log("WebRTC信令连接成功");
      }
    } catch (error) {
      console.error("WebRTC连接失败:", error);
    }
  };
  const disconnectWebRTC = () => {
    webrtcClient.value?.disconnect();
    webrtcClient.value = null;
    webrtcConnected.value = false;
    videoStream.value = null;
  };
  const setVideoElement = (element) => {
    currentVideoElement.value = element;
    if (webrtcClient.value) {
      webrtcClient.value.setVideoElement(element);
    }
  };
  const requestVideoStream = () => {
    if (webrtcClient.value && selectedSourceId.value) {
      webrtcClient.value.requestVideoStream();
    }
  };
  // 应用级操作方法
  const setSelectedSource = (sourceId) => {
    selectedSourceId.value = sourceId;
  };
  // 完整的视频源到分析的工作流
  const setupSourceForAnalysis = async (sourceId) => {
    try {
      globalLoading.value = true;
      // 1. 确保视频源存在并启动RTSP
      const source = videoSourceStore.getVideoSourceById(sourceId);
      if (!source) {
        throw new Error("视频源不存在");
      }
      // 启动RTSP推流
      await videoSourceStore.startRTSP(sourceId);
      // 2. 在分析模块添加对应的RTSP接收源
      const rtspUrl = `rtsp://localhost:8554/${sourceId}`;
      await analysisStore.addAnalysisSource(sourceId, rtspUrl);
      console.log(`视频源 ${sourceId} 已配置用于分析`);
      return true;
    } catch (error) {
      console.error("配置视频源分析失败:", error);
      throw error;
    } finally {
      globalLoading.value = false;
    }
  };
  const startFullAnalysisWorkflow = async (
    sourceId,
    modelId,
    analysisType = "object_detection",
  ) => {
    try {
      globalLoading.value = true;
      // 1. 确保模型已加载
      const model = analysisStore.availableModels.find((m) => m.id === modelId);
      if (!model) {
        throw new Error("模型不存在");
      }
      if (model.status !== "loaded") {
        await analysisStore.loadModel(modelId);
      }
      // 2. 设置视频源用于分析
      await setupSourceForAnalysis(sourceId);
      // 3. 启动分析任务
      const task = await analysisStore.startAnalysis(
        sourceId,
        modelId,
        analysisType,
      );
      console.log(`分析工作流启动成功，任务ID: ${task.task_id}`);
      return task;
    } catch (error) {
      console.error("启动分析工作流失败:", error);
      throw error;
    } finally {
      globalLoading.value = false;
    }
  };
  const stopFullAnalysisWorkflow = async (sourceId) => {
    try {
      globalLoading.value = true;
      // 1. 停止分析任务
      const task = selectedSourceTask.value;
      if (task && task.status === "running") {
        await analysisStore.stopAnalysis(task.task_id);
      }
      // 2. 移除分析源
      await analysisStore.removeAnalysisSource(sourceId);
      // 3. 停止RTSP推流
      await videoSourceStore.stopRTSP(sourceId);
      console.log(`视频源 ${sourceId} 的分析工作流已停止`);
      return true;
    } catch (error) {
      console.error("停止分析工作流失败:", error);
      throw error;
    } finally {
      globalLoading.value = false;
    }
  };
  // 数据刷新
  const refreshAllData = async () => {
    try {
      globalLoading.value = true;
      await Promise.all([
        videoSourceStore.fetchVideoSources(),
        analysisStore.fetchAnalysisTasks(),
        analysisStore.fetchAnalysisResults(),
      ]);
    } catch (error) {
      console.error("刷新数据失败:", error);
    } finally {
      globalLoading.value = false;
    }
  };
  // 初始化整个应用
  const init = async () => {
    if (isInitialized.value) return;
    try {
      globalLoading.value = true;
      // 初始化子stores
      await Promise.all([videoSourceStore.init(), analysisStore.init()]);
      // 设置默认选择的视频源
      if (videoSourceStore.videoSources.length > 0 && !selectedSourceId.value) {
        selectedSourceId.value = videoSourceStore.videoSources[0].id;
      }
      // 初始化WebRTC
      await connectWebRTC();
      // 启动定期数据刷新
      analysisStore.startPeriodicRefresh();
      isInitialized.value = true;
      console.log("应用初始化完成");
    } catch (error) {
      console.error("应用初始化失败:", error);
    } finally {
      globalLoading.value = false;
    }
  };
  return {
    // 状态
    selectedSourceId,
    isInitialized,
    globalLoading,
    // WebRTC状态
    webrtcConnected,
    videoStream,
    currentVideoElement,
    // 计算属性
    selectedSource,
    selectedSourceTask,
    selectedSourceResults,
    isAnalysisRunning,
    // 子stores
    videoSourceStore,
    analysisStore,
    // WebRTC方法
    connectWebRTC,
    disconnectWebRTC,
    setVideoElement,
    requestVideoStream,
    // 应用级方法
    setSelectedSource,
    setupSourceForAnalysis,
    startFullAnalysisWorkflow,
    stopFullAnalysisWorkflow,
    refreshAllData,
    init,
  };
});

