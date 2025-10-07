import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { VideoSource, AnalysisResult, AnalysisType } from "@/types";
import { WebRTCClient, type WebRTCConfig } from "@/utils/webrtc";

const API_BASE = "/api";
const PROFILE_BY_ANALYSIS_TYPE: Record<string, string> = {
  object_detection: "det_720p",
  instance_segmentation: "seg_720p",
};
const DEFAULT_STREAM_URL = "rtsp://127.0.0.1:8554/camera_01";
const DEFAULT_VIDEO_SOURCE: VideoSource = {
  id: "camera_01",
  name: "Camera 01",
  type: "stream",
  url: DEFAULT_STREAM_URL,
  status: "inactive",
  fps: 0,
  resolution: "1280x720",
};

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  status: "loaded" | "available" | "loading" | "error";
  description?: string;
}

export const useVideoStore = defineStore("video", () => {
  // 状态
  const videoSources = ref<VideoSource[]>([{ ...DEFAULT_VIDEO_SOURCE }]);
  const analysisResults = ref<AnalysisResult[]>([]);
  const analysisTypes = ref<AnalysisType[]>([
    { id: "object_detection", name: "目标检测", enabled: true },
    { id: "instance_segmentation", name: "实例分割", enabled: false },
  ]);

  const selectedSourceId = ref<string>(DEFAULT_VIDEO_SOURCE.id);
  const selectedAnalysisType = ref<string>("object_detection");

  // 模型状态
  const availableModels = ref<ModelInfo[]>([]);
  const selectedModelId = ref<string>("");
  const isAnalyzing = ref(false);

  const connectionStatus = ref<"connecting" | "connected" | "disconnected">(
    "disconnected",
  );

  // WebRTC 状态
  const webrtcClient = ref<WebRTCClient | null>(null);
  const webrtcConnected = ref(false);
  const videoStream = ref<MediaStream | null>(null);
  const currentVideoElement = ref<HTMLVideoElement | null>(null);

  // JPEG 视频播放状态
  const jpegVideoPlayer = ref<any>(null);
  const lastFrameTimestamp = ref(0);
  const frameLatency = ref(0);

  // 计算属性
  const activeVideoSources = computed(() =>
    videoSources.value.filter((source) => source.status === "active"),
  );

  const selectedSource = computed(
    () =>
      videoSources.value.find(
        (source) => source.id === selectedSourceId.value,
      ) || null,
  );

  const recentAnalysisResults = computed(() =>
    analysisResults.value
      .filter((result) => result.source_id === selectedSourceId.value)
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, 10),
  );

  const filteredModels = computed(() =>
    availableModels.value.filter(
      (model) => model.type === selectedAnalysisType.value,
    ),
  );

  // 简单的 WebSocket 模拟（保留调试输出）
  const connectWebSocket = () => {
    connectionStatus.value = "connected";
    console.log("[videoStore] mock websocket connected");
  };

  const handleWebSocketMessage = (message: any) => {
    switch (message.type) {
      case "video_sources_update":
        videoSources.value = message.data;
        break;
      case "analysis_result":
        analysisResults.value.unshift(message.data);
        if (analysisResults.value.length > 1000) {
          analysisResults.value = analysisResults.value.slice(0, 1000);
        }
        break;
      case "status_update":
        updateVideoSourceStatus(message.source_id, message.data.status);
        break;
      case "error":
        console.error("[videoStore] backend error:", message.data);
        break;
      default:
        console.log("[videoStore] unknown ws message:", message);
    }
  };

  const updateVideoSourceStatus = (sourceId: string, status: string) => {
    const source = videoSources.value.find((s) => s.id === sourceId);
    if (source) {
      source.status = status as VideoSource["status"];
    }
  };

  const addVideoSource = (source: Omit<VideoSource, "id" | "status">) => {
    const newSource: VideoSource = {
      ...source,
      id: `source_${Date.now()}`,
      status: "active",
    };
    videoSources.value.push(newSource);
    console.log("[videoStore] added source", newSource.name);
  };

  const updateVideoSource = (source: VideoSource) => {
    const index = videoSources.value.findIndex((s) => s.id === source.id);
    if (index > -1) {
      videoSources.value[index] = source;
      console.log("[videoStore] updated source", source.name);
    }
  };

  const removeVideoSource = (sourceId: string) => {
    const index = videoSources.value.findIndex((s) => s.id === sourceId);
    if (index > -1) {
      videoSources.value.splice(index, 1);
      console.log("[videoStore] removed source", sourceId);
    }
  };

  const setSelectedSource = (sourceId: string) => {
    selectedSourceId.value = sourceId;
  };

  const setSelectedAnalysisType = (type: string) => {
    selectedAnalysisType.value = type;
    if (filteredModels.value.length > 0) {
      selectedModelId.value = filteredModels.value[0].id;
    }
  };

  const setSelectedModel = async (modelId: string) => {
    selectedModelId.value = modelId;
    try {
      await apiRequest("/models/load", {
        method: "POST",
        body: JSON.stringify({ model_id: modelId }),
      });
      await fetchModels();
    } catch (error) {
      console.error("[videoStore] failed to load model:", error);
      throw error;
    }
  };

  const getAnalysisStatus = async () => ({
    isAnalyzing: isAnalyzing.value,
    selectedSourceId: selectedSourceId.value,
    selectedModelId: selectedModelId.value,
  });

  const mapModelToInfo = (model: any): ModelInfo => {
    const nameParts = [model.family, model.variant].filter(Boolean);
    const displayName = nameParts.length ? nameParts.join(" / ") : model.id;
    const taskType =
      model.task === "seg" ? "instance_segmentation" : "object_detection";
    const isActive = Boolean(model.active) || (model.active_pipelines ?? 0) > 0;
    return {
      id: model.id,
      name: displayName,
      type: taskType,
      status: isActive ? "loaded" : "available",
      description: model.path,
    };
  };

  const updateAnalysisTypeAvailability = () => {
    const hasDetection = availableModels.value.some(
      (m) => m.type === "object_detection",
    );
    const hasSegmentation = availableModels.value.some(
      (m) => m.type === "instance_segmentation",
    );
    analysisTypes.value = analysisTypes.value.map((type) => {
      if (type.id === "object_detection") {
        return { ...type, enabled: hasDetection };
      }
      if (type.id === "instance_segmentation") {
        return { ...type, enabled: hasSegmentation };
      }
      return type;
    });
  };

  const fetchModels = async () => {
    try {
      const data = await apiRequest<any[]>("/models");
      const list = Array.isArray(data) ? data : [];
      availableModels.value = list.map(mapModelToInfo);
      updateAnalysisTypeAvailability();

      if (!selectedModelId.value && availableModels.value.length > 0) {
        const preferred = availableModels.value.find(
          (model) => model.type === selectedAnalysisType.value,
        );
        selectedModelId.value = (preferred || availableModels.value[0]).id;
      }
    } catch (error) {
      console.error("[videoStore] failed to fetch models:", error);
    }
  };

  const mergePipelinesWithDefaults = (pipelines: any[]): VideoSource[] => {
    const map = new Map<string, VideoSource>();
    map.set(DEFAULT_VIDEO_SOURCE.id, { ...DEFAULT_VIDEO_SOURCE });

    pipelines.forEach((item) => {
      const existing = map.get(item.stream) || {
        id: item.stream,
        name: item.stream,
        type: "stream",
        url: item.source_uri || DEFAULT_STREAM_URL,
        status: "inactive" as VideoSource["status"],
        fps: 0,
        resolution: "1280x720",
      };

      existing.status = item.running ? "active" : "inactive";
      existing.url = item.source_uri || existing.url;
      const width =
        item.encoder?.width || DEFAULT_VIDEO_SOURCE.resolution.split("x")[0];
      const height =
        item.encoder?.height || DEFAULT_VIDEO_SOURCE.resolution.split("x")[1];
      existing.resolution = `${width}x${height}`;
      existing.fps = Number(item.metrics?.fps || existing.fps || 0);

      map.set(existing.id, existing);
    });

    return Array.from(map.values());
  };

  const fetchVideoSources = async () => {
    try {
      const data = await apiRequest<any[]>("/pipelines");
      const list = Array.isArray(data) ? data : [];
      const merged = mergePipelinesWithDefaults(list);
      // Attach per-pipeline zerocopy metrics to sources by id if available
      merged.forEach((src) => {
        const p = list.find((it) => it.track_id === `${src.id}:det_720p` || it.stream_id === src.id || it.key?.startsWith(`${src.id}:`));
        if (p && p.zerocopy_metrics) {
          (src as any).zc = p.zerocopy_metrics;
        }
      });
      videoSources.value = merged;

      if (videoSources.value.length > 0 && !selectedSourceId.value) {
        selectedSourceId.value = videoSources.value[0].id;
      }

      isAnalyzing.value = videoSources.value.some(
        (source) => source.status === "active",
      );
    } catch (error) {
      console.error("[videoStore] failed to fetch pipelines:", error);
      videoSources.value = [{ ...DEFAULT_VIDEO_SOURCE }];
      isAnalyzing.value = false;
    }
  };

  const startAnalysis = async (sourceId: string, analysisType: string) => {
    console.log(
      "[videoStore] start analysis",
      sourceId,
      analysisType,
      "model:",
      selectedModelId.value,
    );

    const targetSourceId = sourceId || selectedSourceId.value;
    if (!targetSourceId) {
      throw new Error("请选择一个视频源");
    }

    const profile =
      PROFILE_BY_ANALYSIS_TYPE[analysisType] ??
      PROFILE_BY_ANALYSIS_TYPE.object_detection;
    if (!profile) {
      throw new Error("当前分析类型尚未配置 profile");
    }

    if (!selectedModelId.value) {
      throw new Error("请先选择一个模型");
    }

    const source =
      videoSources.value.find((s) => s.id === targetSourceId) ||
      DEFAULT_VIDEO_SOURCE;

    await apiRequest("/subscribe", {
      method: "POST",
      body: JSON.stringify({
        stream: targetSourceId,
        profile,
        url: source.url || DEFAULT_STREAM_URL,
        model_id: selectedModelId.value,
      }),
    });

    isAnalyzing.value = true;
    await fetchVideoSources();
    // 无论连接状态，尝试请求一次，已连接则直接触发 offer，未连接则在 onConnected 再请求
    requestVideoStream();
  };

  const stopAnalysis = async (sourceId: string) => {
    console.log("[videoStore] stop analysis", sourceId);

    const targetSourceId = sourceId || selectedSourceId.value;
    if (!targetSourceId) {
      throw new Error("请选择一个视频源");
    }

    const profile =
      PROFILE_BY_ANALYSIS_TYPE[selectedAnalysisType.value] ??
      PROFILE_BY_ANALYSIS_TYPE.object_detection;

    await apiRequest("/unsubscribe", {
      method: "POST",
      body: JSON.stringify({
        stream: targetSourceId,
        profile,
      }),
    });

    isAnalyzing.value = false;
    await fetchVideoSources();
  };

  const initWebRTC = () => {
    const sig =
      (import.meta as any).env?.VITE_SIGNALING_URL ||
      `${location.origin.replace(/^http/, "ws")}/signaling`;
    const config: WebRTCConfig = {
      signalingServerUrl: sig,
      stunServers: [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
      ],
    };

    webrtcClient.value = new WebRTCClient(config);
    webrtcClient.value.setEventHandlers({
      onConnected: () => {
        webrtcConnected.value = true;
        console.log("[videoStore] WebRTC connected");
        if (selectedSourceId.value) {
          requestVideoStream();
        }
      },
      onDisconnected: () => {
        webrtcConnected.value = false;
        videoStream.value = null;
        console.log("[videoStore] WebRTC disconnected");
      },
      onVideoStream: (stream: MediaStream) => {
        videoStream.value = stream;
        if (currentVideoElement.value) {
          currentVideoElement.value.srcObject = stream;
        }
      },
      onError: (error: string) => {
        console.error("[videoStore] WebRTC error:", error);
      },
    });
  };

  const connectWebRTC = async () => {
    if (!webrtcClient.value) {
      initWebRTC();
    }

    try {
      await webrtcClient.value?.connect();
    } catch (error) {
      console.error("[videoStore] WebRTC connect failed:", error);
    }
  };

  const disconnectWebRTC = () => {
    webrtcClient.value?.disconnect();
    webrtcClient.value = null;
    webrtcConnected.value = false;
    videoStream.value = null;
  };

  const setVideoElement = (element: HTMLVideoElement) => {
    currentVideoElement.value = element;
    if (webrtcClient.value) {
      webrtcClient.value.setVideoElement(element);
    }
  };

  const requestVideoStream = () => {
    if (webrtcClient.value && selectedSourceId.value) {
      webrtcClient.value.requestVideoStream(selectedSourceId.value);
    }
  };

  const setJpegVideoPlayer = (player: any) => {
    jpegVideoPlayer.value = player;
  };

  const handleJpegFrame = (jpegData: ArrayBuffer) => {
    const now = performance.now();
    if (lastFrameTimestamp.value > 0) {
      frameLatency.value = now - lastFrameTimestamp.value;
    }
    lastFrameTimestamp.value = now;

    if (jpegVideoPlayer.value) {
      jpegVideoPlayer.value.displayJpegFrame(jpegData);
      jpegVideoPlayer.value.updateLatency(frameLatency.value);

      const latest = recentAnalysisResults.value[0];
      if (latest) {
        jpegVideoPlayer.value.updateDetections(latest.detections || []);
      }
    }
  };

  // 设置后端引擎参数（渲染方式、NMS、IoBinding、Warmup、覆盖器参数等）
  const setEngine = async (options: Record<string, unknown>) => {
    const body = {
      type: "ort-cuda",
      device: 0,
      options,
    };
    await apiRequest("/engine/set", { method: "POST", body: JSON.stringify(body) });
  };

  const init = async () => {
    connectWebSocket();
    connectWebRTC();

    await fetchVideoSources();
    await fetchModels();

    if (!selectedModelId.value && filteredModels.value.length > 0) {
      selectedModelId.value = filteredModels.value[0].id;
    }
  };

  return {
    // 状态
    videoSources,
    analysisResults,
    analysisTypes,
    selectedSourceId,
    selectedAnalysisType,
    connectionStatus,

    // 模型状态
    availableModels,
    selectedModelId,
    isAnalyzing,

    // WebRTC 状态
    webrtcConnected,
    videoStream,
    currentVideoElement,

    // 计算属性
    activeVideoSources,
    selectedSource,
    recentAnalysisResults,
    filteredModels,

    // 操作
    connectWebSocket,
    handleWebSocketMessage,
    addVideoSource,
    updateVideoSource,
    removeVideoSource,
    startAnalysis,
    stopAnalysis,
    setSelectedSource,
    setSelectedAnalysisType,
    setSelectedModel,
    getAnalysisStatus,
    fetchModels,
    fetchVideoSources,
    setEngine,

    // WebRTC 操作
    connectWebRTC,
    disconnectWebRTC,
    setVideoElement,
    requestVideoStream,

    // JPEG 播放
    setJpegVideoPlayer,
    handleJpegFrame,

    init,
  };
});

async function apiRequest<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const init: RequestInit = { ...options };
  const headers: Record<string, string> = {};
  if (options.headers) {
    Object.assign(headers, options.headers as Record<string, string>);
  }
  if (init.body && !("Content-Type" in headers)) {
    headers["Content-Type"] = "application/json";
  }
  if (Object.keys(headers).length > 0) {
    init.headers = headers;
  }

  const response = await fetch(`${API_BASE}${path}`, init);
  const json = await response.json().catch(() => null);

  if (!response.ok) {
    const message = json?.error || json?.message || response.statusText;
    throw new Error(message || "Request failed");
  }

  if (json && json.success === false) {
    throw new Error(json.error || json.message || "Request failed");
  }

  if (json && Object.prototype.hasOwnProperty.call(json, "data")) {
    return json.data as T;
  }
  return json as T;
}
