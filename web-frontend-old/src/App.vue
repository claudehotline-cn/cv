<template>
  <div id="app">
    <el-container>
      <el-header class="header">
        <h1>视频分析系统</h1>
      </el-header>

      <el-container>
        <el-aside width="250px" class="sidebar">
          <el-menu
            default-active="/video-analysis"
            router
            background-color="#545c64"
            text-color="#fff"
            active-text-color="#ffd04b"
          >
            <el-menu-item index="/video-analysis">
              <el-icon><VideoPlay /></el-icon>
              <span>视频分析</span>
            </el-menu-item>
            <el-menu-item index="/video-source-manager">
              <el-icon><Camera /></el-icon>
              <span>视频源管理</span>
            </el-menu-item>
            <el-menu-item index="/analysis-results">
              <el-icon><TrendCharts /></el-icon>
              <span>分析结果</span>
            </el-menu-item>
            <el-menu-item index="/settings">
              <el-icon><Setting /></el-icon>
              <span>系统设置</span>
            </el-menu-item>
          </el-menu>
        </el-aside>

        <el-main class="main-content">
          <RouterView />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { RouterView } from "vue-router";
import {
  Camera,
  TrendCharts,
  Setting,
  VideoPlay,
} from "@element-plus/icons-vue";
</script>

<style scoped>
#app {
  height: 100vh;
  font-family: Arial, sans-serif;
}

.header {
  background-color: #409eff;
  color: white;
  display: flex;
  align-items: center;
  padding: 0 20px;
}

.header h1 {
  margin: 0;
  font-size: 24px;
}

.sidebar {
  background-color: #545c64;
}

.main-content {
  background-color: #f5f5f5;
  padding: 20px;
}
</style>
