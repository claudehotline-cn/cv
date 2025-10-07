  };
};

const getDetectionTagType = (confidence: number) => {
  if (confidence >= 0.8) return "success";
  if (confidence >= 0.6) return "warning";
  return "danger";
};

const goToSourceManager = () => {
  router.push("/video-source-manager");
};

// 模型选择相关方法
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

// WebRTC相关方法
const requestVideoStream = async () => {
  // 如果WebRTC未连接，先重新连接
  if (!videoStore.webrtcConnected) {
    console.log("🔗 WebRTC未连接，正在重新连接...");
    await videoStore.connectWebRTC();
    // 等待连接建立后再请求视频流
    setTimeout(() => {
      videoStore.requestVideoStream();
    }, 1000);
  } else {
    videoStore.requestVideoStream();
  }
};

const stopVideoStream = () => {
  // 断开WebRTC连接
  videoStore.disconnectWebRTC();

  // 清理本地视频元素
  if (videoElement.value) {
    videoElement.value.srcObject = null;
  }

  // 清理JPEG播放器
    
  }

  console.log("🛑 视频流已停止");
};

// JPEG播放器事件处理



};

// 监听视频源变化，更新分析状态并重新请求视频流
watch(
  () => videoStore.selectedSourceId,
  async (newSourceId, oldSourceId) => {
    if (newSourceId && newSourceId !== oldSourceId) {
      console.log("📹 视频源已切换:", oldSourceId, "->", newSourceId);

      // 如果WebRTC已连接，直接请求新源的视频流（不需要断开重连）
      if (videoStore.webrtcConnected) {
        console.log("🔄 保持WebRTC连接，切换到新源:", newSourceId);
        // 稍等一下让selectedSourceId更新完成
        await new Promise((resolve) => setTimeout(resolve, 100));
        videoStore.requestVideoStream();
      } else {
        // 如果未连接，先连接再请求
        console.log("🔗 WebRTC未连接，正在连接并请求新源:", newSourceId);
        await videoStore.connectWebRTC();
        setTimeout(() => {
          videoStore.requestVideoStream();
        }, 1000);
      }

      // 更新分析状态
      await videoStore.getAnalysisStatus();
    }
  },
);

// 生命周期
onMounted(async () => {
  console.log("🎬 VideoAnalysis组件已挂载");
  videoStore.init();

  // 等待WebRTC连接建立和DOM更新
  setTimeout(async () => {
    console.log("🎥 准备设置视频元素和JPEG播放器");

    // 设置JPEG视频播放器
      console.log("📹 找到JPEG播放器，正在设置到store");
      
    } else {
      console.error("❌ JPEG播放器未找到");
    }

    // 设置备用视频元素
    if (videoElement.value) {
      console.log("📹 找到视频元素，正在设置到store");
      videoStore.setVideoElement(videoElement.value);
    }

    // 每个客户端独立：刷新后自动开启分析
    if (videoStore.selectedSourceId) {
      console.log("🎬 自动开启分析（新连接默认开启）");
      try {
        await videoStore.startAnalysis(
          videoStore.selectedSourceId,
