<script setup lang="ts">
import { NButton, NForm, NFormItem, NInput, useMessage } from 'naive-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import loginHero from '@/assets/login-hero.jpg'
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
  <div class="login-page">
    <div class="login-shell">
      <div class="login-visual">
        <img :src="loginHero" alt="" />
        <div class="visual-text">
          <div class="visual-slogan">让每一节课，都落在合适的位置</div>
          <div class="visual-sub">自动排课 · 三视角课表 · 调代课管理</div>
        </div>
      </div>
      <div class="login-form-side">
        <h1 class="form-title">排课与调代课系统</h1>
        <p class="form-sub">请输入帐号与密码登录</p>
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
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  /* 2026-10-30 Jason 定:登录页深蓝太重,改成登录后同一套淡蓝渐变,
     与 MainLayout 应用壳底色完全一致,进出系统不换底色。 */
  background: linear-gradient(180deg, #C7D9F6 0%, #DDE7F8 30%, #E9EBF2 65%, #F5F5F7 100%);
}
.login-shell {
  display: flex;
  width: min(1060px, 100%);
  background: rgba(255, 255, 255, 0.88);
  -webkit-backdrop-filter: saturate(180%) blur(20px); backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 12px 40px rgba(30, 60, 120, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.login-visual {
  position: relative;
  flex: 1.15;
  min-height: 560px;
}
.login-visual::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 45%;
  background: linear-gradient(rgba(8, 47, 66, 0.55), rgba(8, 47, 66, 0));
  pointer-events: none;
}
.login-visual img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.visual-text {
  position: absolute;
  left: 32px;
  right: 32px;
  top: 28px;
  z-index: 1;
  color: #fff;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.45);
}
.visual-slogan {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 1px;
}
.visual-sub {
  margin-top: 8px;
  font-size: 14px;
  opacity: 0.9;
}
.login-form-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px 44px;
}
.form-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}
.form-sub {
  margin: 8px 0 28px;
  color: #8a94a6;
  font-size: 14px;
}
@media (max-width: 860px) {
  .login-visual {
    display: none;
  }
  .login-form-side {
    padding: 36px 28px;
  }
}
</style>
