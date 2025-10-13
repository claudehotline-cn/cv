<template>
  <el-config-provider size="small">
    <el-container class="shell">
      <el-aside width="248px" class="aside">
        <SideNav />
      </el-aside>

      <el-container>
        <el-header height="64px" class="header">
          <TopHeader />
        </el-header>

        <el-main class="main">
          <router-view />
        </el-main>

        <el-footer height="36px" class="footer">
          <FooterBar />
        </el-footer>
      </el-container>
    </el-container>
  </el-config-provider>
  <el-backtop />
</template>

<script setup lang="ts">
import TopHeader from '@/components/chrome/TopHeader.vue'
import SideNav from '@/components/chrome/SideNav.vue'
import FooterBar from '@/components/chrome/FooterBar.vue'
</script>

<style scoped>
.shell { height: 100vh; }
.aside { background: linear-gradient(180deg, #101421, #0c1019); border-right: 1px solid var(--va-border); }
.header{ background: rgba(9, 12, 20, .65); backdrop-filter: blur(6px); border-bottom: 1px solid var(--va-border); }
.main  { padding: 16px; background: var(--va-surface-1); }
.footer{ border-top: 1px solid var(--va-border); color: var(--va-text-2); padding: 6px 12px; }
</style>

