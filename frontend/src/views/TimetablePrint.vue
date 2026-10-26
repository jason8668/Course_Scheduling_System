<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { classLabel } from '@/utils/labels'
import { useRoute } from 'vue-router'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import type { PeriodCell } from '@/components/timetable/types'
import { getPublishedTimetable } from '@/api/timetables'
import type { PublishedTimetable } from '@/api/timetables'
import { getSchoolSettings } from '@/api/assignments'

// 课表打印页(班级/教师/场地三种视角共用):独立一页供 A4 打印张贴,不套侧边栏。
// 显示逻辑与课表查询页一致(节次表选择、跨节次表补列与时间注记、单双周并列),
// 版面比照调代课打印页:校名 + 对象名称课表 + 完整周课表黑框表。

type ViewKind = 'class' | 'teacher' | 'room'

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

const route = useRoute()
const data = ref<PublishedTimetable | null>(null)
const schoolName = ref('')
const loading = ref(true)
const printedAt = new Date().toLocaleString('zh-CN', { hour12: false })

const view = computed<ViewKind>(() => {
  const v = route.query.view as string
  return v === 'teacher' || v === 'room' ? v : 'class'
})
const targetId = computed(() => Number(route.query.id) || null)

const targetName = computed(() => {
  const d = data.value
  if (!d || targetId.value === null) return ''
  if (view.value === 'class') {
    const c = d.classes.find((x) => x.id === targetId.value)
    return c ? classLabel(c) : ''
  }
  const list = view.value === 'teacher' ? d.teachers : d.rooms
  return list.find((x) => x.id === targetId.value)?.name ?? ''
})
const title = computed(() => {
  if (!targetName.value) return '课表'
  return view.value === 'teacher' ? `${targetName.value}老师课表` : `${targetName.value}课表`
})

const defaultTable = computed(() => {
  const ts = data.value?.period_tables ?? []
  return ts.find((t) => t.is_default) ?? ts[0] ?? null
})
/** 班级视角用该班所属节次表;教师/场地视角用学期默认表(同查询页)。 */
const activeTable = computed(() => {
  if (view.value === 'class' && targetId.value) {
    const c = data.value?.classes.find((x) => x.id === targetId.value)
    if (c?.period_table_id) {
      return data.value?.period_tables.find((t) => t.id === c.period_table_id) ?? defaultTable.value
    }
  }
  return defaultTable.value
})
const numWeekdays = computed(() => activeTable.value?.num_weekdays ?? 5)
const weekdays = computed(() => Array.from({ length: numWeekdays.value }, (_, i) => i + 1))
/** 星期多时 A4 横式才不溢出(同课堂巡视情况记录表);五天周用直式。 */
const wide = computed(() => numWeekdays.value > 5)

const shownEntries = computed(() => {
  const all = data.value?.entries ?? []
  if (targetId.value === null) return []
  if (view.value === 'class') return all.filter((e) => e.class_ids.includes(targetId.value!))
  if (view.value === 'teacher') return all.filter((e) => e.teacher_ids.includes(targetId.value!))
  return all.filter((e) => e.room_id === targetId.value)
})
/** 教师/场地视角:默认表没有、但用得到的节次列要补上(同查询页)。 */
const periods = computed<PeriodCell[]>(() => {
  const base = (activeTable.value?.periods ?? []) as PeriodCell[]
  if (view.value === 'class') return base
  return [...base, ...extraRows(
    shownEntries.value, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value,
  ) as PeriodCell[]]
})
const periodNos = computed(() =>
  [...new Set(periods.value.map((p) => p.period_no))].sort((a, b) => a - b))
const periodMap = computed(() => {
  const m = new Map<string, PeriodCell>()
  for (const p of periods.value) m.set(`${p.weekday}-${p.period_no}`, p)
  return m
})
const periodInfo = computed(() => {
  const m = new Map<number, PeriodCell>()
  for (const p of periods.value) if (!m.has(p.period_no)) m.set(p.period_no, p)
  return m
})

interface PrintCell {
  subject: string
  who: string // 班级视角=教师;教师/场地视角=班级
  room?: string
  note?: string
  week?: '单' | '双'
}
const cellMap = computed(() => {
  const m = new Map<string, PrintCell[]>()
  for (const e of shownEntries.value) {
    const cell: PrintCell = {
      subject: e.subject,
      who: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
      room: e.room ?? undefined,
      note: view.value === 'class' ? undefined : crossTableNote(
        e, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value),
      week: e.week_parity === 'odd' ? '单' : e.week_parity === 'even' ? '双' : undefined,
    }
    const k = `${e.weekday}-${e.period_no}`
    m.set(k, [...(m.get(k) ?? []), cell])
  }
  // 单双周同格:单周排前、双周排后
  for (const cells of m.values()) {
    cells.sort((a, b) => (a.week === '单' ? 0 : 1) - (b.week === '单' ? 0 : 1))
  }
  return m
})
/** 连堂的代表格位 → rowspan;被连堂盖住的格位不渲染(同课表网格)。 */
const spanMap = computed(() => {
  const m = new Map<string, number>()
  for (const e of shownEntries.value) {
    const k = `${e.weekday}-${e.period_no}`
    m.set(k, Math.max(m.get(k) ?? 1, e.span ?? 1))
  }
  return m
})
const coveredSet = computed(() => {
  const s = new Set<string>()
  const nos = periodNos.value
  for (const e of shownEntries.value) {
    const span = e.span ?? 1
    if (span <= 1) continue
    const idx = nos.indexOf(e.period_no)
    for (let k = 1; k < span; k++) {
      const pp = nos[idx + k]
      if (pp !== undefined) s.add(`${e.weekday}-${pp}`)
    }
  }
  return s
})

function fmt(t?: string | null): string {
  return t ? t.slice(0, 5) : ''
}
function periodTime(p: number): string {
  const info = periodInfo.value.get(p)
  if (!info?.start_time) return ''
  return `${fmt(info.start_time)}-${fmt(info.end_time)}`
}
function periodAt(w: number, p: number): PeriodCell | undefined {
  return periodMap.value.get(`${w}-${p}`)
}
function isRegular(w: number, p: number): boolean {
  return periodAt(w, p)?.type === 'regular'
}
function cellsAt(w: number, p: number): PrintCell[] {
  return cellMap.value.get(`${w}-${p}`) ?? []
}
function isCovered(w: number, p: number): boolean {
  return coveredSet.value.has(`${w}-${p}`)
}

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  try {
    data.value = await getPublishedTimetable(sid)
  } finally {
    loading.value = false
  }
  // 校名接口仅管理员可读;读不到就不显示校名,不影响其余内容
  try {
    schoolName.value = (await getSchoolSettings()).school_name
  } catch {
    schoolName.value = ''
  }
})
</script>

<template>
  <div class="sheet" :class="{ wide }">
    <div class="no-print toolbar">
      <button type="button" data-testid="tt-print-btn" @click="doPrint">打印</button>
      <button type="button" @click="doClose">关闭</button>
    </div>

    <template v-if="data && targetName">
      <header class="head">
        <h1 v-if="schoolName" class="school">{{ schoolName }}</h1>
        <h2 class="title">{{ title }}</h2>
        <div class="meta">
          <span>{{ data.semester_label }} · {{ data.name }}(已发布)</span>
          <span class="printed">打印时间:{{ printedAt }}</span>
        </div>
      </header>

      <p v-if="!periods.length" class="empty">此学期尚无节次表。</p>
      <table v-else class="grid" data-testid="tt-print-table">
        <thead>
          <tr>
            <th class="pcol">节次</th>
            <th v-for="w in weekdays" :key="w">星期{{ WEEKDAY_LABELS[w - 1] ?? w }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in periodNos" :key="p">
            <td class="pcol">
              <div class="pname">{{ periodInfo.get(p)?.name ?? `第${p}节` }}</div>
              <div class="ptime">{{ periodTime(p) }}</div>
            </td>
            <template v-for="w in weekdays" :key="`${w}-${p}`">
              <td
                v-if="!isCovered(w, p)"
                :rowspan="spanMap.get(`${w}-${p}`) ?? 1"
                :class="{ blocked: periodAt(w, p) && !isRegular(w, p) }"
              >
                <template v-if="!periodAt(w, p)" />
                <span v-else-if="!isRegular(w, p)" class="blocked-label">
                  {{ periodAt(w, p)?.name ?? '—' }}
                </span>
                <template v-else>
                  <div v-for="(c, i) in cellsAt(w, p)" :key="i" class="cell">
                    <div class="subject">
                      <span v-if="c.week" class="week-tag">{{ c.week }}</span>{{ c.subject }}
                    </div>
                    <div v-if="c.who" class="who">{{ c.who }}</div>
                    <div v-if="c.room && view !== 'room'" class="room">{{ c.room }}</div>
                    <div v-if="c.note" class="note">{{ c.note }}</div>
                  </div>
                </template>
              </td>
            </template>
          </tr>
        </tbody>
      </table>
    </template>

    <p v-else-if="loading" class="empty">载入中…</p>
    <p v-else class="empty">课表尚未发布,或指定的班级/教师/场地不存在。</p>
  </div>
</template>

<style scoped>
.sheet {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px;
  color: #000;
  background: #fff;
  font-family: "Microsoft YaHei", "Microsoft JhengHei", "PingFang SC", "PingFang TC", sans-serif;
}
.sheet.wide { max-width: 1120px; }
.toolbar { display: flex; gap: 8px; justify-content: flex-end; margin-bottom: 16px; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.head { text-align: center; margin-bottom: 14px; }
.school { font-size: 22px; margin: 0 0 4px; }
.title { font-size: 19px; font-weight: 600; letter-spacing: 2px; margin: 0 0 8px; }
.meta { display: flex; justify-content: space-between; font-size: 13px; padding: 0 4px; }
.printed { color: #444; }
.grid { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 13px; }
.grid th, .grid td { border: 1px solid #000; padding: 5px 6px; text-align: center; vertical-align: middle; }
.grid th { background: #eee; font-size: 14px; }
.grid .pcol { width: 92px; }
.pname { font-weight: 600; font-size: 13px; }
.ptime { font-size: 11px; color: #444; }
td.blocked { background: #f2f2f2; }
.blocked-label { font-size: 12px; color: #555; }
.cell + .cell { border-top: 1px dashed #999; margin-top: 3px; padding-top: 3px; }
.subject { font-weight: 600; font-size: 14px; }
.week-tag {
  font-size: 11px; font-weight: 700; border: 1px solid #000; border-radius: 3px;
  padding: 0 3px; margin-right: 4px; vertical-align: 1px;
}
.who { font-size: 12px; }
.room { font-size: 11px; color: #444; }
.note { font-size: 11px; font-weight: 600; }
.empty { text-align: center; padding: 40px 0; font-size: 15px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  @page wide { size: A4 landscape; margin: 10mm; }
  .sheet.wide { page: wide; }
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; }
}
</style>
