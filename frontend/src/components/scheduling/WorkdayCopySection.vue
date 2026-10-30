<script setup lang="ts">
/**
 * 调休日课表复制(Jason 2026-10-30 定):
 * 调休上班日每次上哪天的课都不一样(有时周一、有时周五),不能按固定规则猜。
 * 国家接口同步进来的调休日先在校历里标出来;提前 14 天内,管理员在这里
 * 手工选“按周几的课表”,一键把那天的已发布课表复制成当天的单次特殊日规则
 * (发布后即生效),实际课表、课时、提醒都按特殊日展开,不用另起一套。
 * 全校范围特殊日只有管理员能建,年级主任只能看清单、请管理员复制。
 */
import {
  NAlert, NButton, NEmpty, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { listWorkdays } from '@/api/calendar'
import type { Workday } from '@/api/calendar'
import { getPublishedTimetable } from '@/api/timetables'
import type { PublishedTimetable } from '@/api/timetables'
import { getSemester as getSemesterDetail } from '@/api/semesters'
import {
  WEEKDAY_LABELS, createSpecialDayRule, publishSpecialDayRule,
} from '@/api/specialDays'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ semesterId: number | null }>()
const message = useMessage()
const auth = useAuthStore()
const isAdmin = computed(() => auth.hasRole('admin'))

const workdays = ref<Workday[]>([])
const published = ref<PublishedTimetable | null>(null)
const semesterStart = ref<string | null>(null)
const loading = ref(true)
const copying = ref<string | null>(null)
// 每条调休日各自选的源周几,默认周五(最常见),管理员可改
const sourceWeekday = ref<Record<string, number>>({})

function localDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
function daysUntil(dateStr: string): number {
  const today = new Date(localDate(new Date()))
  const target = new Date(`${dateStr}T00:00:00`)
  return Math.round((target.getTime() - today.getTime()) / 86400000)
}
/** 目标日的单双周(与后端 week_number 同款:学期首日所在周的周一为第 1 周周一)。 */
function targetParity(dateStr: string): 'odd' | 'even' | null {
  if (!semesterStart.value) return null
  const start = new Date(`${semesterStart.value}T00:00:00`)
  const firstMonday = new Date(start)
  firstMonday.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  const target = new Date(`${dateStr}T00:00:00`)
  const week = Math.floor((target.getTime() - firstMonday.getTime()) / 86400000 / 7) + 1
  return week % 2 === 1 ? 'odd' : 'even'
}

const upcoming = computed(() => workdays.value
  .filter((w) => daysUntil(w.date) >= 0)
  .sort((a, b) => a.date.localeCompare(b.date)))
const pendingUrgent = computed(() => upcoming.value.filter(
  (w) => !w.has_copy && daysUntil(w.date) <= 14,
))

async function load() {
  const sid = props.semesterId
  if (sid === null) return
  loading.value = true
  try {
    const [wd, pub, sem] = await Promise.all([
      listWorkdays(sid),
      getPublishedTimetable(sid).catch(() => null),
      getSemesterDetail(sid).catch(() => null),
    ])
    workdays.value = wd
    published.value = pub
    semesterStart.value = sem?.start_date ?? null
    for (const w of wd) {
      if (!(w.date in sourceWeekday.value)) sourceWeekday.value[w.date] = 5
    }
  } catch {
    // 调休清单加载失败不挡排课中心其他部分,下面空状态说明
    workdays.value = []
  } finally {
    loading.value = false
  }
}

async function onCopy(w: Workday) {
  const sid = props.semesterId
  const pub = published.value
  if (sid === null || !pub) {
    message.warning('本学期还没有已发布的课表,无法复制')
    return
  }
  const src = sourceWeekday.value[w.date] ?? 5
  const parity = targetParity(w.date)
  const seen = new Set<string>()
  const entries: { class_unit_id: number; period_no: number; course_assignment_id: number }[] = []
  for (const e of pub.entries) {
    if (e.weekday !== src) continue
    if (parity && e.week_parity && e.week_parity !== parity) continue
    for (let p = e.period_no; p < e.period_no + (e.span || 1); p++) {
      for (const cid of e.class_ids) {
        const key = `${cid}-${p}`
        if (seen.has(key)) continue
        seen.add(key)
        entries.push({ class_unit_id: cid, period_no: p, course_assignment_id: e.course_assignment_id })
      }
    }
  }
  if (!entries.length) {
    message.warning(`按${WEEKDAY_LABELS[src]}的课表那天没有课,复制不了`)
    return
  }
  copying.value = w.date
  try {
    const rule = await createSpecialDayRule(sid, {
      title: `${w.title}:按${WEEKDAY_LABELS[src]}课表`,
      scope_type: 'school',
      scope_id: null,
      recurrence: 'single',
      single_date: w.date,
      weekday: null,
      day_of_month: null,
      start_date: null,
      end_date: null,
      entries,
    })
    await publishSpecialDayRule(rule.id)
    message.success(`已复制${entries.length}节(按${WEEKDAY_LABELS[src]}课表),${w.date}实际课表已生效`)
    await load()
  } catch (e) {
    message.error((e as Error).message || '复制失败')
  } finally {
    copying.value = null
  }
}

watch(() => props.semesterId, load)
onMounted(load)
</script>

<template>
  <section class="ios-section">
    <div class="ios-section-title">调休日课表复制</div>
    <div class="ios-card">
      <div class="ios-card-body">
        <div class="ios-row-sub">
          调休上班日每次上哪天的课都不一样,系统不猜:国家时间表同步进来的调休日列在这里,
          提前 14 天内会醒目提醒,管理员选“按周几的课表”一键复制成当天的特殊日,实际课表即生效。
        </div>
        <n-alert v-if="pendingUrgent.length && isAdmin" type="warning" style="margin-top: 8px">
          {{ pendingUrgent.length }} 个调休日在 14 天内还没复制课表,请尽快复制。
        </n-alert>
        <n-alert v-else-if="pendingUrgent.length && !isAdmin" type="warning" style="margin-top: 8px">
          {{ pendingUrgent.length }} 个调休日在 14 天内还没复制课表,请联系管理员复制。
        </n-alert>
        <n-empty v-if="!loading && !upcoming.length" description="本学期暂无调休上班日" style="margin-top: 8px" />
        <div v-for="w in upcoming" :key="w.date" class="ios-row" data-testid="workday-row">
          <div class="ios-row-main">
            <div class="ios-row-title">
              {{ w.date }} {{ WEEKDAY_LABELS[new Date(`${w.date}T00:00:00`).getDay() === 0 ? 7 : new Date(`${w.date}T00:00:00`).getDay()] }}
              {{ w.title }}
            </div>
            <div class="ios-row-sub">
              <template v-if="w.has_copy">已复制课表,实际课表按复制的课上</template>
              <template v-else-if="daysUntil(w.date) <= 14">
                还有 {{ daysUntil(w.date) }} 天,请复制课表
              </template>
              <template v-else>还有 {{ daysUntil(w.date) }} 天,到 14 天内会提醒</template>
            </div>
          </div>
          <n-space v-if="!w.has_copy && isAdmin" align="center" :wrap="true">
            <n-select
              :value="sourceWeekday[w.date] ?? 5"
              :options="Object.entries(WEEKDAY_LABELS).map(([k, v]) => ({ label: `按${v}课表`, value: Number(k) }))"
              style="width: 140px" data-testid="workday-source"
              @update:value="(v: number) => { sourceWeekday[w.date] = v }"
            />
            <n-button
              type="primary" size="small" :loading="copying === w.date"
              data-testid="workday-copy" @click="onCopy(w)"
            >
              复制课表
            </n-button>
          </n-space>
          <n-tag v-else-if="w.has_copy" type="success" size="small">已复制</n-tag>
        </div>
        <n-text v-if="!isAdmin" depth="3" style="font-size: 12px">
          全校调休复制只有管理员能操作,主任如需调整请联系管理员。
        </n-text>
      </div>
    </div>
  </section>
</template>
