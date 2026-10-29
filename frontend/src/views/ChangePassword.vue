<script setup lang="ts">
import { NButton, NForm, NFormItem, NInput, NSpace, NText, useMessage } from 'naive-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()

const MIN_LEN = 8
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)

// 首次登录是被导过来的(不能离开);其余是用户自己从右上角进来改,可以取消
const forced = computed(() => auth.mustChangePassword)

function onCancel() {
  router.back()
}

async function onSubmit() {
  // 送出中就不再受理:避免连点两下送出两次改密请求——第二次必然因为密码已被改掉而
  // 回「原密码错误」,用户会同时看到成功与失败两则讯息。
  if (loading.value) return
  if (newPassword.value.length < MIN_LEN) {
    message.warning(`新密码至少需 ${MIN_LEN} 个字元`)
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    message.warning('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    message.success('密码已更新')
    router.push({ name: 'dashboard' })
  } catch (e) {
    message.error((e as ApiError).detail || '变更密码失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px">
    <div class="ios-card" style="width: 100%; max-width: 420px">
      <div class="ios-card-body">
        <h1 class="ios-title" style="margin-bottom: 8px">变更密码</h1>
        <n-text v-if="forced" depth="3" style="display: block; margin-bottom: 12px" data-testid="cp-forced">
          这是您的首次登录,请设置新密码后继续使用系统。
        </n-text>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="原密码">
          <n-input
            v-model:value="oldPassword" type="password" show-password-on="click"
            data-testid="cp-old"
          />
        </n-form-item>
        <n-form-item :label="`新密码(至少 ${MIN_LEN} 字元)`">
          <n-input
            v-model:value="newPassword" type="password" show-password-on="click"
            data-testid="cp-new"
          />
        </n-form-item>
        <n-form-item label="确认新密码">
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            data-testid="cp-confirm"
          />
        </n-form-item>
        <!-- 送出只走表单的 submit 这一条路(按钮是 type=submit,输入框按 Enter 也会触发它)。
             先前按钮另外挂了 @click、确认栏另外挂了 @keyup.enter,于是每次送出都跑两遍。 -->
        <n-space vertical size="small">
          <n-button type="primary" block :loading="loading" attr-type="submit" data-testid="cp-submit">
            更新密码
          </n-button>
          <n-button v-if="!forced" block quaternary data-testid="cp-cancel" @click="onCancel">
            取消
          </n-button>
        </n-space>
      </n-form>
      </div>
    </div>
  </div>
</template>
