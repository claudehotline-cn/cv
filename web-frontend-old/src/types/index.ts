export interface VideoSource {
  id: string;
  name: string;
  type: "camera" | "file" | "stream";
  url: string;
  status: "active" | "inactive" | "error";
  fps: number;
  resolution: string;
  zc?: ZeroCopyMetrics;
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

export interface ZeroCopyMetrics {
  d2d_nv12_frames: number;
  cpu_fallback_skips: number;
  eagain_retry_count: number;
  overlay_nv12_kernel_hits: number;
  overlay_nv12_passthrough: number;
}
