          videoStore.selectedAnalysisType,
        );
      } catch (error) {
        console.error("自动开启分析失败:", error);
      }
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
