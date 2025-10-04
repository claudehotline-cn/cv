export interface VideoSource {
  id: string;
  name: string;
  type: "camera" | "file" | "stream";
  url: string;
  status: "active" | "inactive" | "error";
  fps: number;
  resolution: string;
}

export interface AnalysisType {
  id: string;
  name: string;
  enabled: boolean;
}

export interface DetectionResult {
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  confidence: number;
  class_id: number;
  class_name: string;
}

export interface AnalysisResult {
  source_id: string;
  timestamp: number;
  type: "object_detection" | "instance_segmentation";
  detections: DetectionResult[];
  request_id?: string;
  processed_image_url?: string;
  segmentation_mask_url?: string;
}

export interface WebSocketMessage {
  type: "video_frame" | "analysis_result" | "status_update" | "error";
  source_id?: string;
  data: any;
  timestamp: number;
}

export interface EngineRuntimeStatus {
  provider: string;
  gpu_active: boolean;
  io_binding: boolean;
  device_binding: boolean;
  cpu_fallback: boolean;
}

export interface EngineOptions {
  use_io_binding: boolean;
  prefer_pinned_memory: boolean;
  allow_cpu_fallback: boolean;
  enable_profiling: boolean;
  tensorrt_fp16: boolean;
  tensorrt_int8: boolean;
  tensorrt_workspace_mb: number;
  io_binding_input_bytes: number;
  io_binding_output_bytes: number;
}

export interface SystemEngineInfo {
  type: string;
  device: string;
  options: Partial<EngineOptions>;
}

export interface SystemInfo {
  engine?: SystemEngineInfo;
  engine_runtime?: EngineRuntimeStatus;
  model_count?: number;
  profile_count?: number;
  [key: string]: unknown;
}
