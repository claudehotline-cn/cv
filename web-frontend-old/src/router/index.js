import { createRouter, createWebHistory } from "vue-router";
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      redirect: "/video-source-manager",
    },
    {
      path: "/video-source-manager",
      name: "VideoSourceManager",
      component: () => import("@/views/VideoSourceManager.vue"),
    },
    {
      path: "/video-analysis",
      name: "VideoAnalysis",
      component: () => import("@/views/VideoAnalysis.vue"),
    },
    {
      path: "/video-streams",
      redirect: "/video-analysis",
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
    }
  ],
});
export default router;
