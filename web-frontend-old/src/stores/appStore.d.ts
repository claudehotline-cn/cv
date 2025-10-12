export declare const useAppStore: import("pinia").StoreDefinition<
  "app",
  Pick<
    {
      selectedSourceId: import("vue").Ref<string, string>;
      isInitialized: import("vue").Ref<boolean, boolean>;
      globalLoading: import("vue").Ref<boolean, boolean>;
      webrtcConnected: import("vue").Ref<boolean, boolean>;
      videoStream: import("vue").Ref<
        {
          readonly active: boolean;
          readonly id: string;
          onaddtrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          onremovetrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          addTrack: (track: MediaStreamTrack) => void;
          clone: () => MediaStream;
          getAudioTracks: () => MediaStreamTrack[];
          getTrackById: (trackId: string) => MediaStreamTrack | null;
          getTracks: () => MediaStreamTrack[];
          getVideoTracks: () => MediaStreamTrack[];
          removeTrack: (track: MediaStreamTrack) => void;
          addEventListener: {
            <K extends keyof MediaStreamEventMap>(
              type: K,
              listener: (this: MediaStream, ev: MediaStreamEventMap[K]) => any,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
          };
          removeEventListener: {
            <K_1 extends keyof MediaStreamEventMap>(
              type: K_1,
              listener: (
                this: MediaStream,
                ev: MediaStreamEventMap[K_1],
              ) => any,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
          };
          dispatchEvent: (event: Event) => boolean;
        } | null,
        | MediaStream
        | {
            readonly active: boolean;
            readonly id: string;
            onaddtrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            onremovetrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            addTrack: (track: MediaStreamTrack) => void;
            clone: () => MediaStream;
            getAudioTracks: () => MediaStreamTrack[];
            getTrackById: (trackId: string) => MediaStreamTrack | null;
            getTracks: () => MediaStreamTrack[];
            getVideoTracks: () => MediaStreamTrack[];
            removeTrack: (track: MediaStreamTrack) => void;
            addEventListener: {
              <K extends keyof MediaStreamEventMap>(
                type: K,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K],
                ) => any,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
            };
            removeEventListener: {
              <K_1 extends keyof MediaStreamEventMap>(
                type: K_1,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K_1],
                ) => any,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
            };
            dispatchEvent: (event: Event) => boolean;
          }
        | null
      >;
      currentVideoElement: import("vue").Ref<
        HTMLVideoElement | null,
        HTMLVideoElement | null
      >;
      selectedSource: import("vue").ComputedRef<
        | {
            id: string;
            name: string;
            type: "camera" | "file" | "stream";
            url: string;
            status: "active" | "inactive" | "error";
            fps: number;
            resolution: string;
          }
        | undefined
      >;
      selectedSourceTask: import("vue").ComputedRef<
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "error" | "running" | "stopped";
            start_time: number;
            frames_processed: number;
            avg_fps: number;
          }
        | undefined
      >;
      selectedSourceResults: import("vue").ComputedRef<
        {
          source_id: string;
          timestamp: number;
          type: "object_detection" | "instance_segmentation";
          detections: {
            bbox: {
              x: number;
              y: number;
              width: number;
              height: number;
            };
            confidence: number;
            class_id: number;
            class_name: string;
          }[];
          request_id?: number | undefined;
          processed_image_url?: string | undefined;
          segmentation_mask_url?: string | undefined;
        }[]
      >;
      isAnalysisRunning: import("vue").ComputedRef<boolean>;
      videoSourceStore: import("pinia").Store<
        "videoSource",
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "error" | "loading" | "videoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "activeVideoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          | "getSystemInfo"
          | "init"
          | "fetchVideoSources"
          | "addVideoSource"
          | "updateVideoSource"
          | "deleteVideoSource"
          | "getVideoSourceInfo"
          | "startRTSP"
          | "stopRTSP"
          | "getRTSPStatus"
          | "getVideoSourceStats"
          | "getVideoSourceById"
        >
      >;
      analysisStore: import("pinia").Store<
        "analysis",
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "error"
          | "loading"
          | "analysisResults"
          | "analysisTasks"
          | "availableModels"
          | "analysisSources"
          | "analysisTypes"
          | "selectedModelId"
          | "selectedAnalysisType"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "runningTasks"
          | "loadedModels"
          | "activeAnalysisSources"
          | "recentAnalysisResults"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "fetchModels"
          | "loadModel"
          | "unloadModel"
          | "getModelInfo"
          | "fetchAnalysisTasks"
          | "startAnalysis"
          | "stopAnalysis"
          | "getAnalysisStatus"
          | "fetchAnalysisResults"
          | "fetchAnalysisSources"
          | "addAnalysisSource"
          | "removeAnalysisSource"
          | "getSystemInfo"
          | "getPerformanceStats"
          | "getTaskBySourceId"
          | "getResultsBySourceId"
          | "startPeriodicRefresh"
          | "init"
        >
      >;
      connectWebRTC: () => Promise<void>;
      disconnectWebRTC: () => void;
      setVideoElement: (element: HTMLVideoElement) => void;
      requestVideoStream: () => void;
      setSelectedSource: (sourceId: string) => void;
      setupSourceForAnalysis: (sourceId: string) => Promise<boolean>;
      startFullAnalysisWorkflow: (
        sourceId: string,
        modelId: string,
        analysisType?: string,
      ) => Promise<import("./analysisStore").AnalysisTask>;
      stopFullAnalysisWorkflow: (sourceId: string) => Promise<boolean>;
      refreshAllData: () => Promise<void>;
      init: () => Promise<void>;
    },
    | "selectedSourceId"
    | "isInitialized"
    | "globalLoading"
    | "webrtcConnected"
    | "videoStream"
    | "currentVideoElement"
    | "videoSourceStore"
    | "analysisStore"
  >,
  Pick<
    {
      selectedSourceId: import("vue").Ref<string, string>;
      isInitialized: import("vue").Ref<boolean, boolean>;
      globalLoading: import("vue").Ref<boolean, boolean>;
      webrtcConnected: import("vue").Ref<boolean, boolean>;
      videoStream: import("vue").Ref<
        {
          readonly active: boolean;
          readonly id: string;
          onaddtrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          onremovetrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          addTrack: (track: MediaStreamTrack) => void;
          clone: () => MediaStream;
          getAudioTracks: () => MediaStreamTrack[];
          getTrackById: (trackId: string) => MediaStreamTrack | null;
          getTracks: () => MediaStreamTrack[];
          getVideoTracks: () => MediaStreamTrack[];
          removeTrack: (track: MediaStreamTrack) => void;
          addEventListener: {
            <K extends keyof MediaStreamEventMap>(
              type: K,
              listener: (this: MediaStream, ev: MediaStreamEventMap[K]) => any,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
          };
          removeEventListener: {
            <K_1 extends keyof MediaStreamEventMap>(
              type: K_1,
              listener: (
                this: MediaStream,
                ev: MediaStreamEventMap[K_1],
              ) => any,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
          };
          dispatchEvent: (event: Event) => boolean;
        } | null,
        | MediaStream
        | {
            readonly active: boolean;
            readonly id: string;
            onaddtrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            onremovetrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            addTrack: (track: MediaStreamTrack) => void;
            clone: () => MediaStream;
            getAudioTracks: () => MediaStreamTrack[];
            getTrackById: (trackId: string) => MediaStreamTrack | null;
            getTracks: () => MediaStreamTrack[];
            getVideoTracks: () => MediaStreamTrack[];
            removeTrack: (track: MediaStreamTrack) => void;
            addEventListener: {
              <K extends keyof MediaStreamEventMap>(
                type: K,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K],
                ) => any,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
            };
            removeEventListener: {
              <K_1 extends keyof MediaStreamEventMap>(
                type: K_1,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K_1],
                ) => any,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
            };
            dispatchEvent: (event: Event) => boolean;
          }
        | null
      >;
      currentVideoElement: import("vue").Ref<
        HTMLVideoElement | null,
        HTMLVideoElement | null
      >;
      selectedSource: import("vue").ComputedRef<
        | {
            id: string;
            name: string;
            type: "camera" | "file" | "stream";
            url: string;
            status: "active" | "inactive" | "error";
            fps: number;
            resolution: string;
          }
        | undefined
      >;
      selectedSourceTask: import("vue").ComputedRef<
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "error" | "running" | "stopped";
            start_time: number;
            frames_processed: number;
            avg_fps: number;
          }
        | undefined
      >;
      selectedSourceResults: import("vue").ComputedRef<
        {
          source_id: string;
          timestamp: number;
          type: "object_detection" | "instance_segmentation";
          detections: {
            bbox: {
              x: number;
              y: number;
              width: number;
              height: number;
            };
            confidence: number;
            class_id: number;
            class_name: string;
          }[];
          request_id?: number | undefined;
          processed_image_url?: string | undefined;
          segmentation_mask_url?: string | undefined;
        }[]
      >;
      isAnalysisRunning: import("vue").ComputedRef<boolean>;
      videoSourceStore: import("pinia").Store<
        "videoSource",
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "error" | "loading" | "videoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "activeVideoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          | "getSystemInfo"
          | "init"
          | "fetchVideoSources"
          | "addVideoSource"
          | "updateVideoSource"
          | "deleteVideoSource"
          | "getVideoSourceInfo"
          | "startRTSP"
          | "stopRTSP"
          | "getRTSPStatus"
          | "getVideoSourceStats"
          | "getVideoSourceById"
        >
      >;
      analysisStore: import("pinia").Store<
        "analysis",
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "error"
          | "loading"
          | "analysisResults"
          | "analysisTasks"
          | "availableModels"
          | "analysisSources"
          | "analysisTypes"
          | "selectedModelId"
          | "selectedAnalysisType"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "runningTasks"
          | "loadedModels"
          | "activeAnalysisSources"
          | "recentAnalysisResults"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "fetchModels"
          | "loadModel"
          | "unloadModel"
          | "getModelInfo"
          | "fetchAnalysisTasks"
          | "startAnalysis"
          | "stopAnalysis"
          | "getAnalysisStatus"
          | "fetchAnalysisResults"
          | "fetchAnalysisSources"
          | "addAnalysisSource"
          | "removeAnalysisSource"
          | "getSystemInfo"
          | "getPerformanceStats"
          | "getTaskBySourceId"
          | "getResultsBySourceId"
          | "startPeriodicRefresh"
          | "init"
        >
      >;
      connectWebRTC: () => Promise<void>;
      disconnectWebRTC: () => void;
      setVideoElement: (element: HTMLVideoElement) => void;
      requestVideoStream: () => void;
      setSelectedSource: (sourceId: string) => void;
      setupSourceForAnalysis: (sourceId: string) => Promise<boolean>;
      startFullAnalysisWorkflow: (
        sourceId: string,
        modelId: string,
        analysisType?: string,
      ) => Promise<import("./analysisStore").AnalysisTask>;
      stopFullAnalysisWorkflow: (sourceId: string) => Promise<boolean>;
      refreshAllData: () => Promise<void>;
      init: () => Promise<void>;
    },
    | "selectedSource"
    | "selectedSourceTask"
    | "selectedSourceResults"
    | "isAnalysisRunning"
  >,
  Pick<
    {
      selectedSourceId: import("vue").Ref<string, string>;
      isInitialized: import("vue").Ref<boolean, boolean>;
      globalLoading: import("vue").Ref<boolean, boolean>;
      webrtcConnected: import("vue").Ref<boolean, boolean>;
      videoStream: import("vue").Ref<
        {
          readonly active: boolean;
          readonly id: string;
          onaddtrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          onremovetrack:
            | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
            | null;
          addTrack: (track: MediaStreamTrack) => void;
          clone: () => MediaStream;
          getAudioTracks: () => MediaStreamTrack[];
          getTrackById: (trackId: string) => MediaStreamTrack | null;
          getTracks: () => MediaStreamTrack[];
          getVideoTracks: () => MediaStreamTrack[];
          removeTrack: (track: MediaStreamTrack) => void;
          addEventListener: {
            <K extends keyof MediaStreamEventMap>(
              type: K,
              listener: (this: MediaStream, ev: MediaStreamEventMap[K]) => any,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | AddEventListenerOptions | undefined,
            ): void;
          };
          removeEventListener: {
            <K_1 extends keyof MediaStreamEventMap>(
              type: K_1,
              listener: (
                this: MediaStream,
                ev: MediaStreamEventMap[K_1],
              ) => any,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
            (
              type: string,
              listener: EventListenerOrEventListenerObject,
              options?: boolean | EventListenerOptions | undefined,
            ): void;
          };
          dispatchEvent: (event: Event) => boolean;
        } | null,
        | MediaStream
        | {
            readonly active: boolean;
            readonly id: string;
            onaddtrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            onremovetrack:
              | ((this: MediaStream, ev: MediaStreamTrackEvent) => any)
              | null;
            addTrack: (track: MediaStreamTrack) => void;
            clone: () => MediaStream;
            getAudioTracks: () => MediaStreamTrack[];
            getTrackById: (trackId: string) => MediaStreamTrack | null;
            getTracks: () => MediaStreamTrack[];
            getVideoTracks: () => MediaStreamTrack[];
            removeTrack: (track: MediaStreamTrack) => void;
            addEventListener: {
              <K extends keyof MediaStreamEventMap>(
                type: K,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K],
                ) => any,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | AddEventListenerOptions | undefined,
              ): void;
            };
            removeEventListener: {
              <K_1 extends keyof MediaStreamEventMap>(
                type: K_1,
                listener: (
                  this: MediaStream,
                  ev: MediaStreamEventMap[K_1],
                ) => any,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
              (
                type: string,
                listener: EventListenerOrEventListenerObject,
                options?: boolean | EventListenerOptions | undefined,
              ): void;
            };
            dispatchEvent: (event: Event) => boolean;
          }
        | null
      >;
      currentVideoElement: import("vue").Ref<
        HTMLVideoElement | null,
        HTMLVideoElement | null
      >;
      selectedSource: import("vue").ComputedRef<
        | {
            id: string;
            name: string;
            type: "camera" | "file" | "stream";
            url: string;
            status: "active" | "inactive" | "error";
            fps: number;
            resolution: string;
          }
        | undefined
      >;
      selectedSourceTask: import("vue").ComputedRef<
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "error" | "running" | "stopped";
            start_time: number;
            frames_processed: number;
            avg_fps: number;
          }
        | undefined
      >;
      selectedSourceResults: import("vue").ComputedRef<
        {
          source_id: string;
          timestamp: number;
          type: "object_detection" | "instance_segmentation";
          detections: {
            bbox: {
              x: number;
              y: number;
              width: number;
              height: number;
            };
            confidence: number;
            class_id: number;
            class_name: string;
          }[];
          request_id?: number | undefined;
          processed_image_url?: string | undefined;
          segmentation_mask_url?: string | undefined;
        }[]
      >;
      isAnalysisRunning: import("vue").ComputedRef<boolean>;
      videoSourceStore: import("pinia").Store<
        "videoSource",
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "error" | "loading" | "videoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          "activeVideoSources"
        >,
        Pick<
          {
            videoSources: import("vue").Ref<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[],
              | import("../types").VideoSource[]
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            activeVideoSources: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: "camera" | "file" | "stream";
                url: string;
                status: "active" | "inactive" | "error";
                fps: number;
                resolution: string;
              }[]
            >;
            fetchVideoSources: () => Promise<void>;
            addVideoSource: (
              source: Omit<import("../types").VideoSource, "id" | "status">,
            ) => Promise<any>;
            updateVideoSource: (
              id: string,
              updates: Partial<import("../types").VideoSource>,
            ) => Promise<any>;
            deleteVideoSource: (id: string) => Promise<void>;
            getVideoSourceInfo: (id: string) => Promise<any>;
            startRTSP: (id: string) => Promise<any>;
            stopRTSP: (id: string) => Promise<any>;
            getRTSPStatus: (id: string) => Promise<any>;
            getVideoSourceStats: (id: string) => Promise<any>;
            getSystemInfo: () => Promise<any>;
            getVideoSourceById: (id: string) =>
              | {
                  id: string;
                  name: string;
                  type: "camera" | "file" | "stream";
                  url: string;
                  status: "active" | "inactive" | "error";
                  fps: number;
                  resolution: string;
                }
              | undefined;
            init: () => Promise<void>;
          },
          | "getSystemInfo"
          | "init"
          | "fetchVideoSources"
          | "addVideoSource"
          | "updateVideoSource"
          | "deleteVideoSource"
          | "getVideoSourceInfo"
          | "startRTSP"
          | "stopRTSP"
          | "getRTSPStatus"
          | "getVideoSourceStats"
          | "getVideoSourceById"
        >
      >;
      analysisStore: import("pinia").Store<
        "analysis",
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "error"
          | "loading"
          | "analysisResults"
          | "analysisTasks"
          | "availableModels"
          | "analysisSources"
          | "analysisTypes"
          | "selectedModelId"
          | "selectedAnalysisType"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "runningTasks"
          | "loadedModels"
          | "activeAnalysisSources"
          | "recentAnalysisResults"
        >,
        Pick<
          {
            analysisResults: import("vue").Ref<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[],
              | import("../types").AnalysisResult[]
              | {
                  source_id: string;
                  timestamp: number;
                  type: "object_detection" | "instance_segmentation";
                  detections: {
                    bbox: {
                      x: number;
                      y: number;
                      width: number;
                      height: number;
                    };
                    confidence: number;
                    class_id: number;
                    class_name: string;
                  }[];
                  request_id?: number | undefined;
                  processed_image_url?: string | undefined;
                  segmentation_mask_url?: string | undefined;
                }[]
            >;
            analysisTasks: import("vue").Ref<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[],
              | import("./analysisStore").AnalysisTask[]
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }[]
            >;
            availableModels: import("vue").Ref<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[],
              | import("./analysisStore").ModelInfo[]
              | {
                  id: string;
                  name: string;
                  type: string;
                  status: "error" | "loaded" | "available" | "loading";
                  format: string;
                  accuracy?: number | undefined;
                  inference_time_ms?: number | undefined;
                }[]
            >;
            analysisSources: import("vue").Ref<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[],
              | import("./analysisStore").AnalysisSource[]
              | {
                  source_id: string;
                  rtsp_url: string;
                  status: "active" | "inactive";
                  analysis_enabled: boolean;
                  fps: number;
                  resolution: string;
                }[]
            >;
            analysisTypes: import("vue").Ref<
              {
                id: string;
                name: string;
                enabled: boolean;
              }[],
              | import("../types").AnalysisType[]
              | {
                  id: string;
                  name: string;
                  enabled: boolean;
                }[]
            >;
            loading: import("vue").Ref<boolean, boolean>;
            error: import("vue").Ref<string | null, string | null>;
            selectedModelId: import("vue").Ref<string, string>;
            selectedAnalysisType: import("vue").Ref<string, string>;
            runningTasks: import("vue").ComputedRef<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            loadedModels: import("vue").ComputedRef<
              {
                id: string;
                name: string;
                type: string;
                status: "error" | "loaded" | "available" | "loading";
                format: string;
                accuracy?: number | undefined;
                inference_time_ms?: number | undefined;
              }[]
            >;
            activeAnalysisSources: import("vue").ComputedRef<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            recentAnalysisResults: import("vue").ComputedRef<
              {
                source_id: string;
                timestamp: number;
                type: "object_detection" | "instance_segmentation";
                detections: {
                  bbox: {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                  };
                  confidence: number;
                  class_id: number;
                  class_name: string;
                }[];
                request_id?: number | undefined;
                processed_image_url?: string | undefined;
                segmentation_mask_url?: string | undefined;
              }[]
            >;
            fetchModels: () => Promise<void>;
            loadModel: (modelId: string) => Promise<void>;
            unloadModel: (modelId: string) => Promise<void>;
            getModelInfo: (
              modelId: string,
            ) => Promise<import("./analysisStore").ModelInfo>;
            fetchAnalysisTasks: () => Promise<
              {
                task_id: string;
                source_id: string;
                model_id: string;
                analysis_type: string;
                status: "error" | "running" | "stopped";
                start_time: number;
                frames_processed: number;
                avg_fps: number;
              }[]
            >;
            startAnalysis: (
              sourceId: string,
              modelId: string,
              analysisType: string,
            ) => Promise<import("./analysisStore").AnalysisTask>;
            stopAnalysis: (taskId: string) => Promise<void>;
            getAnalysisStatus: (taskId: string) => Promise<unknown>;
            fetchAnalysisResults: (
              taskId?: string | undefined,
              limit?: number,
            ) => Promise<import("../types").AnalysisResult[]>;
            fetchAnalysisSources: () => Promise<
              {
                source_id: string;
                rtsp_url: string;
                status: "active" | "inactive";
                analysis_enabled: boolean;
                fps: number;
                resolution: string;
              }[]
            >;
            addAnalysisSource: (
              sourceId: string,
              rtspUrl: string,
            ) => Promise<import("./analysisStore").AnalysisSource>;
            removeAnalysisSource: (sourceId: string) => Promise<void>;
            getSystemInfo: () => Promise<unknown>;
            getPerformanceStats: () => Promise<unknown>;
            getTaskBySourceId: (sourceId: string) =>
              | {
                  task_id: string;
                  source_id: string;
                  model_id: string;
                  analysis_type: string;
                  status: "error" | "running" | "stopped";
                  start_time: number;
                  frames_processed: number;
                  avg_fps: number;
                }
              | undefined;
            getResultsBySourceId: (
              sourceId: string,
              limit?: number,
            ) => {
              source_id: string;
              timestamp: number;
              type: "object_detection" | "instance_segmentation";
              detections: {
                bbox: {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                };
                confidence: number;
                class_id: number;
                class_name: string;
              }[];
              request_id?: number | undefined;
              processed_image_url?: string | undefined;
              segmentation_mask_url?: string | undefined;
            }[];
            startPeriodicRefresh: (interval?: number) => () => void;
            init: () => Promise<void>;
          },
          | "fetchModels"
          | "loadModel"
          | "unloadModel"
          | "getModelInfo"
          | "fetchAnalysisTasks"
          | "startAnalysis"
          | "stopAnalysis"
          | "getAnalysisStatus"
          | "fetchAnalysisResults"
          | "fetchAnalysisSources"
          | "addAnalysisSource"
          | "removeAnalysisSource"
          | "getSystemInfo"
          | "getPerformanceStats"
          | "getTaskBySourceId"
          | "getResultsBySourceId"
          | "startPeriodicRefresh"
          | "init"
        >
      >;
      connectWebRTC: () => Promise<void>;
      disconnectWebRTC: () => void;
      setVideoElement: (element: HTMLVideoElement) => void;
      requestVideoStream: () => void;
      setSelectedSource: (sourceId: string) => void;
      setupSourceForAnalysis: (sourceId: string) => Promise<boolean>;
      startFullAnalysisWorkflow: (
        sourceId: string,
        modelId: string,
        analysisType?: string,
      ) => Promise<import("./analysisStore").AnalysisTask>;
      stopFullAnalysisWorkflow: (sourceId: string) => Promise<boolean>;
      refreshAllData: () => Promise<void>;
      init: () => Promise<void>;
    },
    | "init"
    | "connectWebRTC"
    | "disconnectWebRTC"
    | "setVideoElement"
    | "requestVideoStream"
    | "setSelectedSource"
    | "setupSourceForAnalysis"
    | "startFullAnalysisWorkflow"
    | "stopFullAnalysisWorkflow"
    | "refreshAllData"
  >
>;
