<template>
  <el-config-provider size="small">
    <el-container class="shell">
      <!-- 顶部 Header：全宽 -->
      <el-header height="64px" class="header" v-show="!app.fullscreenEditor">
        <TopHeader  />
      </el-header>

      <!-- 中间：侧栏 + 主内容 -->
      <el-container class="content">
        <el-aside :width="collapsed ? '64px' : '248px'" class="aside" v-show="!app.fullscreenEditor">
          <SideNav :collapsed="collapsed" @toggle="collapsed = !collapsed" />
        </el-aside>
        <el-main class="main" :class="{ fullscreen: app.fullscreenEditor }">
          <BreadcrumbBar v-show="!app.fullscreenEditor" />
          <router-view />
        </el-main>
      </el-container>

      <!-- 底部 Footer：全宽 -->
      <el-footer height="36px" class="footer" v-show="!app.fullscreenEditor">
        <FooterBar />
      </el-footer>
    </el-container>
  </el-config-provider>
  <el-backtop />
  </template>

<script setup lang="ts">
import TopHeader from '@/components/chrome/TopHeader.vue'
import SideNav from '@/components/chrome/SideNav.vue'
import FooterBar from '@/components/chrome/FooterBar.vue'
import BreadcrumbBar from '@/components/chrome/BreadcrumbBar.vue'
import { useAppStore } from '@/stores/app'
import { ref } from 'vue'
const app = useAppStore()
const collapsed = ref(false)
</script>

<style scoped>
.shell { height: 100vh; width: 100%; overflow: hidden; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; min-height: 0; min-width: 0; overflow-x: hidden; }
.aside { position: relative; background: linear-gradient(180deg, #101421, #0c1019); border-right: 1px solid var(--va-border); overflow: hidden; }
.header{ width: 100%; background: rgba(9, 12, 20, .65); backdrop-filter: blur(6px); border-bottom: 1px solid var(--va-border); box-sizing: border-box; }
.main  { height: 100%; padding: 16px; background: var(--va-surface-1); box-sizing: border-box; overflow-x: hidden; min-width: 0; }
.main.fullscreen { padding: 0; }
.footer{ width: 100%; border-top: 1px solid var(--va-border); color: var(--va-text-2); padding: 6px 12px; box-sizing: border-box; }
</style>

<style>
/* 全局防横向滚动条（避免 100vw 与滚动条宽度造成溢出） */
html, body, #app { max-width: 100%; overflow-x: hidden; }
</style>





