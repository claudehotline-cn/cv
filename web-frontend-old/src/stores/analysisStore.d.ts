import type { AnalysisResult, AnalysisType } from "@/types";
export interface AnalysisTask {
  task_id: string;
  source_id: string;
  model_id: string;
  analysis_type: string;
  status: "running" | "stopped" | "error";
  start_time: number;
  frames_processed: number;
  avg_fps: number;
}
export interface ModelInfo {
  id: string;
  name: string;
  type: string;
  status: "loaded" | "available" | "loading" | "error";
  format: string;
  accuracy?: number;
  inference_time_ms?: number;
}
export interface AnalysisSource {
  source_id: string;
  rtsp_url: string;
  status: "active" | "inactive";
  analysis_enabled: boolean;
  fps: number;
  resolution: string;
}
export declare const useAnalysisStore: import("pinia").StoreDefinition<
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
        | AnalysisResult[]
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
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[],
        | AnalysisTask[]
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
          format: string;
          accuracy?: number | undefined;
          inference_time_ms?: number | undefined;
        }[],
        | ModelInfo[]
        | {
            id: string;
            name: string;
            type: string;
            status: "loaded" | "available" | "loading" | "error";
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
        | AnalysisSource[]
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
        | AnalysisType[]
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
          status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
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
      getModelInfo: (modelId: string) => Promise<ModelInfo>;
      fetchAnalysisTasks: () => Promise<
        {
          task_id: string;
          source_id: string;
          model_id: string;
          analysis_type: string;
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[]
      >;
      startAnalysis: (
        sourceId: string,
        modelId: string,
        analysisType: string,
      ) => Promise<AnalysisTask>;
      stopAnalysis: (taskId: string) => Promise<void>;
      getAnalysisStatus: (taskId: string) => Promise<unknown>;
      fetchAnalysisResults: (
        taskId?: string,
        limit?: number,
      ) => Promise<AnalysisResult[]>;
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
      ) => Promise<AnalysisSource>;
      removeAnalysisSource: (sourceId: string) => Promise<void>;
      getSystemInfo: () => Promise<unknown>;
      getPerformanceStats: () => Promise<unknown>;
      getTaskBySourceId: (sourceId: string) =>
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
        | AnalysisResult[]
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
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[],
        | AnalysisTask[]
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
          format: string;
          accuracy?: number | undefined;
          inference_time_ms?: number | undefined;
        }[],
        | ModelInfo[]
        | {
            id: string;
            name: string;
            type: string;
            status: "loaded" | "available" | "loading" | "error";
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
        | AnalysisSource[]
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
        | AnalysisType[]
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
          status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
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
      getModelInfo: (modelId: string) => Promise<ModelInfo>;
      fetchAnalysisTasks: () => Promise<
        {
          task_id: string;
          source_id: string;
          model_id: string;
          analysis_type: string;
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[]
      >;
      startAnalysis: (
        sourceId: string,
        modelId: string,
        analysisType: string,
      ) => Promise<AnalysisTask>;
      stopAnalysis: (taskId: string) => Promise<void>;
      getAnalysisStatus: (taskId: string) => Promise<unknown>;
      fetchAnalysisResults: (
        taskId?: string,
        limit?: number,
      ) => Promise<AnalysisResult[]>;
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
      ) => Promise<AnalysisSource>;
      removeAnalysisSource: (sourceId: string) => Promise<void>;
      getSystemInfo: () => Promise<unknown>;
      getPerformanceStats: () => Promise<unknown>;
      getTaskBySourceId: (sourceId: string) =>
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
        | AnalysisResult[]
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
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[],
        | AnalysisTask[]
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
          format: string;
          accuracy?: number | undefined;
          inference_time_ms?: number | undefined;
        }[],
        | ModelInfo[]
        | {
            id: string;
            name: string;
            type: string;
            status: "loaded" | "available" | "loading" | "error";
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
        | AnalysisSource[]
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
        | AnalysisType[]
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
          status: "running" | "stopped" | "error";
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
          status: "loaded" | "available" | "loading" | "error";
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
      getModelInfo: (modelId: string) => Promise<ModelInfo>;
      fetchAnalysisTasks: () => Promise<
        {
          task_id: string;
          source_id: string;
          model_id: string;
          analysis_type: string;
          status: "running" | "stopped" | "error";
          start_time: number;
          frames_processed: number;
          avg_fps: number;
        }[]
      >;
      startAnalysis: (
        sourceId: string,
        modelId: string,
        analysisType: string,
      ) => Promise<AnalysisTask>;
      stopAnalysis: (taskId: string) => Promise<void>;
      getAnalysisStatus: (taskId: string) => Promise<unknown>;
      fetchAnalysisResults: (
        taskId?: string,
        limit?: number,
      ) => Promise<AnalysisResult[]>;
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
      ) => Promise<AnalysisSource>;
      removeAnalysisSource: (sourceId: string) => Promise<void>;
      getSystemInfo: () => Promise<unknown>;
      getPerformanceStats: () => Promise<unknown>;
      getTaskBySourceId: (sourceId: string) =>
        | {
            task_id: string;
            source_id: string;
            model_id: string;
            analysis_type: string;
            status: "running" | "stopped" | "error";
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
