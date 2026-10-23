<script setup lang="ts">
// 通知单打印页:调课单(v1.2.2)与代课单(v1.2.5),一张一页(A4 直式)。
// 版面照使用学校现行的纸本:周课表,只在有异动的格子写「日期/科目/第三行」。
// 两种单子格线相同,差在抬头与表头栏位:代课单多了请假教师、假别、计费方式。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getSubstituteSlips, getSwapSlips } from '@/api/substitutions'
import type { Slip, SlipCell, SlipRow, Slips } from '@/api/substitutions'

const DAY_NAMES = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']

const route = useRoute()
const data = ref<Slips | null>(null)
const error = ref('')
const loading = ref(true)

const isSwap = computed(() => !route.path.startsWith('/substitute-slips'))

// 一周一页:跨周的调课(例如本周与隔三周对调)会印成同一位老师/班级的两页
const pages = computed(() =>
  (data.value?.slips ?? []).flatMap((slip) => slip.weeks.map((week) => ({ slip, week }))))

function heading(slip: Slip): string {
  if (isSwap.value) return `●${slip.kind === 'teacher' ? '教师' : '班级'}调课通知单●`
  return slip.kind === 'teacher' ? '代课　通知单' : '班级代课　通知单'
}

function rowsOf(slip: Slip): SlipRow[] {
  if (slip.rows.length) return slip.rows
  // 节次表查不到时退而求其次:依格子用到的最大节次画列,没有时间
  const max = Math.max(1, ...slip.weeks.flatMap((w) => w.cells.map((c) => c.ordinal)))
  return Array.from({ length: max }, (_, i) => ({
    ordinal: i + 1, start_time: null, end_time: null, afternoon_starts: false,
  }))
}

function cellsAt(cells: SlipCell[], day: string, ordinal: number): SlipCell[] {
  return cells.filter((c) => c.date === day && c.ordinal === ordinal)
}

const hhmm = (t: string | null) => (t ? t.slice(0, 5) : '')

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  const ids = String(route.query.ids ?? '').split(',').map(Number).filter(Boolean)
  const fetch = isSwap.value ? getSwapSlips : getSubstituteSlips
  try {
    data.value = await fetch(sid, ids)
  } catch (e) {
    error.value = (e as ApiError).message || (isSwap.value ? '无法产生调课单' : '无法产生代课单')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="slips">
    <div class="no-print toolbar">
      <span v-if="data" class="hint">共 {{ pages.length }} 张</span>
      <button type="button" data-testid="slips-print" @click="doPrint">打印</button>
      <button type="button" @click="doClose">关闭</button>
    </div>

    <p v-if="loading" class="msg">载入中…</p>
    <p v-else-if="error" class="msg" data-testid="slips-error">{{ error }}</p>

    <section
      v-for="({ slip, week }, i) in pages" :key="i" class="page"
      :data-testid="slip.kind === 'teacher' ? 'slip-teacher' : 'slip-class'"
    >
      <!-- 调课单:校名一行、单别一行;代课单照纸本把校名与单别排成一行 -->
      <template v-if="isSwap">
        <h1 class="school">{{ data?.title }}</h1>
        <h2 class="kind">{{ heading(slip) }}</h2>
      </template>
      <h1 v-else class="school one-line">{{ data?.title }}　{{ heading(slip) }}</h1>

      <div v-if="isSwap && slip.kind === 'teacher'" class="meta">
        <div class="meta-line">
          <span class="big">调课教师：{{ slip.teacher_name }}</span>
          <span class="big">调课班级：{{ slip.class_names }}</span>
        </div>
        <div class="small">调课日期：{{ slip.date_from }}~{{ slip.date_to }}</div>
      </div>
      <div v-else-if="isSwap" class="meta meta-line">
        <span class="big">调课班级：{{ slip.class_names }}</span>
        <span class="small">调课日期：{{ slip.date_from }}~{{ slip.date_to }}</span>
      </div>
      <div v-else class="meta">
        <div class="meta-line">
          <span v-if="slip.kind === 'teacher'" class="big">代课教师：{{ slip.teacher_name }}</span>
          <span v-else class="big">代课班级：{{ slip.class_names }}</span>
          <span class="big">请假教师：{{ slip.absent_teacher_name }}</span>
        </div>
        <div class="meta-line small" data-testid="slip-leave-meta">
          <span>日期：{{ slip.date_from }} ~ {{ slip.date_to }}</span>
          <span>假别：{{ slip.leave_type_name }}</span>
          <span>计费方式：{{ slip.funding_label || '—' }}</span>
        </div>
      </div>

      <table class="grid">
        <colgroup>
          <col style="width: 7%">
          <col style="width: 10%">
          <col v-for="day in week.days" :key="day">
        </colgroup>
        <thead>
          <tr>
            <th colspan="2" class="corner">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <line x1="0" y1="0" x2="100" y2="100" vector-effect="non-scaling-stroke" />
              </svg>
            </th>
            <th v-for="(day, d) in week.days" :key="day">
              {{ DAY_NAMES[d] }}<br><span class="date">{{ day }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rowsOf(slip)" :key="row.ordinal"
            :class="{ afternoon: row.afternoon_starts }"
          >
            <td class="ordinal">{{ row.ordinal }}</td>
            <td class="time">
              <template v-if="row.start_time">
                {{ hhmm(row.start_time) }}<br>|<br>{{ hhmm(row.end_time) }}
              </template>
            </td>
            <td v-for="day in week.days" :key="day" class="cell">
              <div
                v-for="(c, k) in cellsAt(week.cells, day, row.ordinal)" :key="k"
                data-testid="slip-cell"
              >
                {{ c.date }}<br>{{ c.subject_name }}<br>{{ c.actor }}
                <template v-if="c.code"><br>[{{ c.code }}]</template>
                <template v-if="c.time_note"><br><b data-testid="slip-time-note">{{ c.time_note }}</b></template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.slips {
  color: #000;
  background: #fff;
  font-family: "DFKai-SB", "BiauKai", "标楷体", "Kaiti TC", serif;
}
.toolbar { display: flex; gap: 8px; justify-content: flex-end; align-items: center; padding: 16px 24px 0; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.hint { color: #555; font-size: 14px; }
.msg { text-align: center; padding: 40px 0; font-size: 15px; }
.page { max-width: 720px; margin: 0 auto; padding: 32px 24px; }
.page + .page { border-top: 1px dashed #bbb; }
.school { font-size: 22px; font-weight: normal; text-align: center; margin: 0; }
.school.one-line { margin-bottom: 18px; }
.kind { font-size: 20px; font-weight: normal; text-align: center; margin: 2px 0 18px; }
.meta { margin-bottom: 18px; }
.meta-line { display: flex; justify-content: space-between; align-items: baseline; }
.big { font-size: 19px; }
.small { font-size: 13px; margin-top: 6px; }
.grid {
  width: 100%; border-collapse: collapse; table-layout: fixed; border: 4px double #000;
}
.grid th, .grid td { border: 1px solid #000; text-align: center; vertical-align: middle; }
.grid th { font-weight: normal; font-size: 14px; height: 72px; border-bottom-width: 2px; }
.grid .date { font-size: 13px; }
/* 斜线用 SVG 画在格子内容里:用背景画的话,浏览器打印默认不印背景,纸本上会变空白格 */
.corner { position: relative; padding: 0; }
.corner svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.corner line { stroke: #000; stroke-width: 1; }
.grid td { height: 70px; font-size: 13px; line-height: 1.35; }
.grid td.ordinal { font-size: 20px; }
.grid td.time { font-size: 11px; line-height: 1.2; }
.grid td.time { border-right-width: 2px; }
tr.afternoon td { border-top-width: 2px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; break-after: page; }
  .page + .page { border-top: none; }
  .page:last-child { break-after: auto; }
}
</style>
