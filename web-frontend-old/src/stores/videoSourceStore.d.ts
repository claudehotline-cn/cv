import type { VideoSource } from "@/types";
export declare const useVideoSourceStore: import("pinia").StoreDefinition<
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
        | VideoSource[]
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
        source: Omit<VideoSource, "id" | "status">,
      ) => Promise<any>;
      updateVideoSource: (
        id: string,
        updates: Partial<VideoSource>,
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
        | VideoSource[]
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
        source: Omit<VideoSource, "id" | "status">,
      ) => Promise<any>;
      updateVideoSource: (
        id: string,
        updates: Partial<VideoSource>,
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
        | VideoSource[]
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
        source: Omit<VideoSource, "id" | "status">,
      ) => Promise<any>;
      updateVideoSource: (
        id: string,
        updates: Partial<VideoSource>,
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
