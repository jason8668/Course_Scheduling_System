<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NSwitch, NSelect, useMessage,
} from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { getReminderPreference, saveReminderPreference } from '@/api/teacherHome'
import type { ReminderPreference } from '@/api/teacherHome'
import DutyRosterSection from '@/components/scheduling/DutyRosterSection.vue'

// 仪表板上的教师个人节(2026-10-30 Jason 再定):
// 请假已在调课管理页、代课与调课也已搬到调课管理页、通知改成仪表板右上角小框,
// 故这里只剩提醒设置 + 行政值日(值日只给行政岗位/管理员显示,见 DutyRosterSection)。
const props = defineProps<{ semesterId: number; teacherId?: number | null }>()
const message = useMessage()

const preference = ref<ReminderPreference | null>(null)
const remindEnabled = ref(true)
const leadSelect = ref<string | number>('follow')
const remindPhone = ref('')
const savingPref = ref(false)

async function loadAll() {
  const pref = await getReminderPreference(props.semesterId).catch(() => null)
  preference.value = pref
  if (pref) {
    remindEnabled.value = pref.reminder_enabled
    leadSelect.value = pref.reminder_lead_minutes ?? 'follow'
    remindPhone.value = pref.phone ?? ''
  }
}

async function savePref() {
  if (!preference.value?.bound) return
  savingPref.value = true
  try {
    const lead = leadSelect.value === 'follow' ? null : Number(leadSelect.value)
    preference.value = await saveReminderPreference(props.semesterId, {
      reminder_enabled: remindEnabled.value,
      reminder_lead_minutes: lead,
      phone: remindPhone.value.trim() || null,
    })
    // 保存时后端已立刻匹配过一次钉钉:绑上当场报已绑定,没绑上当场说明原因,
    // 不用等到下一节课才知道。
    if (preference.value.phone && preference.value.dingtalk_bound) {
      message.success('提醒设置已保存,钉钉已绑定')
    } else if (preference.value.phone) {
      message.warning('提醒设置已保存,但钉钉未绑定:手机号可能不在企业通讯录,或钉钉应用未配置,请联系管理员核对')
    } else {
      message.success('提醒设置已保存')
    }
  } catch (e) {
    message.error((e as Error).message || '保存失败')
  } finally {
    savingPref.value = false
  }
}

onMounted(() => { void loadAll() })
watch(() => props.semesterId, () => { void loadAll() })
</script>

<template>
  <div data-testid="teacher-home-sections">
    <n-alert v-if="preference && !preference.bound" type="warning" title="尚未绑定教师档案" style="margin-top: 16px">
      系统里还没有把你的账号对应到教师档案，请联系管理员开通；课表与提醒需要绑定后才能显示。
    </n-alert>

    <DutyRosterSection :semester-id="semesterId" :admin="false" :teacher-id="teacherId" />

    <section class="ios-section" style="animation-delay: 240ms">
      <div class="ios-section-title">
        <span>提醒设置</span>
      </div>
      <div class="ios-card">
        <n-empty v-if="!preference" description="暂无提醒设置" style="padding: 24px 0" />
        <template v-else>
          <n-alert v-if="!preference.bound" type="warning" style="margin: 12px 16px 0">
            尚未绑定教师档案，提醒设置需要绑定后才能保存。
          </n-alert>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">上课提醒</span>
            <n-switch v-model:value="remindEnabled" :disabled="!preference.bound" />
          </div>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">提前</span>
            <n-select
              v-model:value="leadSelect" :disabled="!preference.bound || !remindEnabled"
              :options="[
                { label: `跟随学校设置（${preference.global_lead_minutes}分钟）`, value: 'follow' },
                { label: '5 分钟', value: 5 },
                { label: '10 分钟', value: 10 },
                { label: '15 分钟', value: 15 },
                { label: '30 分钟', value: 30 },
              ]" style="width: 220px"
            />
          </div>
          <div class="ios-row">
            <span class="ios-row-main" style="font-size: 15px">手机号</span>
            <n-input
              v-model:value="remindPhone" :disabled="!preference.bound" placeholder="钉钉通讯录里的手机号"
              style="width: 200px"
            />
            <span :class="preference.dingtalk_bound ? 'ios-chip-green ios-chip' : 'ios-chip-warn ios-chip'">
              {{ preference.dingtalk_bound ? '钉钉已绑定' : '钉钉未绑定' }}
            </span>
          </div>
          <div class="ios-card-body">
            <div class="ios-row-sub" style="margin-bottom: 8px">
              关了就不会收到上课提醒；保存时立刻匹配一次钉钉,绑上马上显示已绑定,没绑上多半是手机号不在企业通讯录,或钉钉应用未配置。
            </div>
            <n-button type="primary" round :loading="savingPref" :disabled="!preference.bound" @click="savePref">
              保存提醒设置
            </n-button>
          </div>
        </template>
      </div>
    </section>
  </div>
</template>
