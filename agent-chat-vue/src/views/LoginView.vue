<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const submitting = ref(false)
const form = reactive({
  email: '',
  password: '',
})

async function onSubmit() {
  if (!form.email || !form.password) {
    ElMessage.warning('请输入邮箱和密码')
    return
  }

  submitting.value = true
  try {
    await authStore.login(form.email, form.password)
    ElMessage.success('登录成功')
    const target = (route.query.redirect as string) || '/'
    await router.replace(target)
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || '登录失败'
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="hover">
      <h2>Agent Platform 登录</h2>
      <p class="sub">请使用账号登录后访问控制台</p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="you@example.com" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-button type="primary" class="w-full" :loading="submitting" @click="onSubmit">
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 420px;
}

h2 {
  margin: 0 0 8px;
}

.sub {
  margin: 0 0 20px;
  color: #64748b;
}

.w-full {
  width: 100%;
}
</style>
