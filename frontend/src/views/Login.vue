<script setup lang="ts">
import { NButton, NCard, NForm, NFormItem, NInput, useMessage } from 'naive-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onSubmit() {
  if (loading.value) return // 上一笔还没回来:不重复送出(连按、连按 Enter)
  if (!username.value || !password.value) {
    message.warning('请输入帐号与密码')
    return
  }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    // 首次登录需改密码者导向改密码页,否则进仪表板
    router.push(auth.mustChangePassword ? { name: 'change-password' } : { name: 'dashboard' })
  } catch (e) {
    message.error((e as ApiError).detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px">
    <n-card title="排课与调代课系统" style="max-width: 400px">
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="帐号">
          <n-input v-model:value="username" placeholder="请输入帐号" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
          />
        </n-form-item>
        <!-- 送出只走表单的 submit 这一条路(按钮是 type=submit,输入框按 Enter 也会触发它)。
             先前按钮另外挂了 @click、输入框另外挂了 @keyup.enter,按一次送出两笔登录请求:
             输错密码一次算两次失败,约第 3 次就被锁定(用户回报 #39)。 -->
        <n-button type="primary" block :loading="loading" attr-type="submit">
          登录
        </n-button>
      </n-form>
    </n-card>
  </div>
</template>
