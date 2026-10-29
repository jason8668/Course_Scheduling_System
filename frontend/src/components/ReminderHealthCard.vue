<script setup lang="ts">
import { NButton, NCard, NSpace, NTag, NText } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { getReminderHealth } from '@/api/reminderHealth'
import type { ReminderHealth } from '@/api/reminderHealth'

const health = ref<ReminderHealth | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    health.value = await getReminderHealth()
  } catch {
    error.value = '读取健康状态失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function fmtTime(s: string | null): string {
  if (!s) return '还没有成功发送过'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <n-card title="上课提醒健康" data-testid="reminder-health-card">
    <n-space vertical>
      <n-text depth="3">
        提醒链一眼看完：配置、排程任务、最近发送、关提醒与未解析的老师。全部学期合计；只读，不发消息。
      </n-text>
      <n-text v-if="error" type="error">
        {{ error }}
      </n-text>
      <template v-else-if="health">
        <n-space align="center" :wrap="true">
          <n-tag :type="health.configured ? 'success' : 'error'" size="small">
            {{ health.configured ? '企业应用已配置' : '企业应用未配置' }}
          </n-tag>
          <n-tag
            :type="health.job_scheduled === true ? 'success' : health.job_scheduled === false ? 'error' : 'warning'"
            size="small"
          >
            {{ health.job_scheduled === true ? '提醒任务已排入' : health.job_scheduled === false ? '提醒任务未排入' : '排程状态查不到' }}
          </n-tag>
          <n-text depth="3" style="font-size: 13px">
            全局提前 {{ health.lead_minutes }} 分钟 · 最近发送 {{ fmtTime(health.last_sent_at) }} ·
            近 7 天发送 {{ health.sent_7d }} 条
          </n-text>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text depth="2" style="font-size: 13px">
            有手机号 {{ health.teachers_with_phone }} 人 · 无手机号 {{ health.teachers_missing_phone }} 人
          </n-text>
          <n-text v-if="health.opted_out.length" depth="2" style="font-size: 13px">
            关提醒 {{ health.opted_out.length }} 人：{{ health.opted_out.map((t) => t.name).join('、') }}
          </n-text>
          <n-text v-if="health.unresolved.length" type="warning" style="font-size: 13px">
            有手机但钉钉里找不到人 {{ health.unresolved.length }} 人：{{ health.unresolved.map((t) => t.name).join('、') }}
            ——请检查手机号是否在钉钉通讯录里
          </n-text>
        </n-space>
      </template>
      <n-space>
        <n-button size="small" :loading="loading" @click="load">
          刷新
        </n-button>
      </n-space>
    </n-space>
  </n-card>
</template>
