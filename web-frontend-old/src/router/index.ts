import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      redirect: "/video-analysis",
    },
    {
      path: "/video-analysis",
      name: "VideoAnalysis",
      component: () => import("@/views/VideoAnalysis.vue"),
    },
    {
      path: "/video-source-manager",
      name: "VideoSourceManager",
      component: () => import("@/views/VideoSourceManager.vue"),
    },
    {
      path: "/analysis-results",
      name: "AnalysisResults",
      component: () => import("@/views/AnalysisResults.vue"),
    },
    {
      path: "/settings",
      name: "Settings",
      component: () => import("@/views/Settings.vue"),
    },
    {
      path: "/jpeg-test",
      name: "JpegTest",
      component: () => import("@/views/JpegVideoTest.vue"),
    },
  ],
});

export default router;
