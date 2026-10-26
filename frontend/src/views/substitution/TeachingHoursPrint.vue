<script setup lang="ts">
// 教学课时统计打印页(A4 直式):按年级分组打印每个老师的课时数,最后附总计。
// 与查询页共用同一接口,查询条件由路由 query 传入。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import { gradeLabel } from '@/api/substitutionLog'
import { getTeachingHours } from '@/api/teachingHours'
import type { HoursScope, TeachingHoursReport } from '@/api/teachingHours'

const route = useRoute()
const report = ref<TeachingHoursReport | null>(null)
const semesterLabel = ref('')
const error = ref('')
const loading = ref(true)

const scopeLabel = computed(() => {
  const s = String(route.query.scope ?? 'semester')
  return s === 'week' ? '本周' : s === 'custom' ? '自选日期' : '一学期'
})

/** 按年级分组:每组列出该年级有课时的老师与节数。 */
const gradeGroups = computed(() => {
  const grades = new Set<number>()
  for (const t of report.value?.teachers ?? []) {
    for (const g of Object.keys(t.by_grade)) grades.add(Number(g))
  }
  return [...grades].sort((a, b) => a - b).map((g) => ({
    grade: g,
    rows: (report.value?.teachers ?? [])
      .filter((t) => (t.by_grade[String(g)] ?? 0) > 0)
      .map((t) => ({ name: t.teacher_name, periods: t.by_grade[String(g)] ?? 0 })),
  })).filter((grp) => grp.rows.length > 0)
})

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  try {
    const sems = await listSemesters().catch(() => [])
    semesterLabel.value = sems.find((s) => s.id === sid)?.label ?? ''
    report.value = await getTeachingHours({
      semester_id: sid,
      scope: (String(route.query.scope ?? 'semester') as HoursScope),
      date_from: route.query.date_from ? String(route.query.date_from) : null,
      date_to: route.query.date_to ? String(route.query.date_to) : null,
      teacher_id: route.query.teacher_id ? Number(route.query.teacher_id) : null,
      grade: route.query.grade ? Number(route.query.grade) : null,
    })
  } catch (e) {
    error.value = (e as ApiError).message || '无法产生教学课时统计'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="hours-print">
    <div class="no-print toolbar">
      <button type="button" data-testid="hours-print-do" @click="doPrint">打印</button>
      <button type="button" @click="doClose">关闭</button>
    </div>

    <p v-if="loading" class="msg">载入中…</p>
    <p v-else-if="error" class="msg" data-testid="hours-print-error">{{ error }}</p>

    <section v-else-if="report" class="page">
      <h1 class="title">
        <span class="school">教学课时统计</span>
        <span>{{ semesterLabel }} · {{ scopeLabel }}</span>
      </h1>
      <p class="sub">
        实际统计期间 {{ report.effective_from }} ~ {{ report.effective_to }}
        （未来日期不计入已上课时）
      </p>

      <div v-for="grp in gradeGroups" :key="grp.grade" class="group">
        <h2>{{ gradeLabel(grp.grade) }}教师课时数</h2>
        <table class="grid">
          <thead>
            <tr><th>教师</th><th>课时（节）</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in grp.rows" :key="r.name">
              <td>{{ r.name }}</td><td>{{ r.periods }}</td>
            </tr>
            <tr class="total">
              <td>合计</td>
              <td>{{ grp.rows.reduce((n, r) => n + r.periods, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="group">
        <h2>总计</h2>
        <table class="grid">
          <thead>
            <tr><th>教师</th><th>总课时（节）</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in report.teachers" :key="t.teacher_id">
              <td>{{ t.teacher_name }}</td><td>{{ t.total }}</td>
            </tr>
            <tr class="total">
              <td>合计</td><td>{{ report.total_periods }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!report.teachers.length" class="msg">该范围内没有已上课时。</p>
    </section>
  </div>
</template>

<style scoped>
.hours-print { font-family: inherit; }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
.toolbar button { cursor: pointer; padding: 6px 16px; }
.msg { color: #666; }
.page { max-width: 760px; margin: 0 auto; padding: 24px; }
.title {
  display: flex; gap: 18px; align-items: baseline; margin: 0 0 6px;
  font-size: 16px; font-weight: normal;
}
.title .school { font-size: 19px; font-weight: bold; }
.sub { font-size: 13px; color: #444; margin: 0 0 16px; }
.group { margin-bottom: 18px; break-inside: avoid; }
.group h2 { font-size: 15px; margin: 0 0 6px; }
.grid { width: 100%; border-collapse: collapse; border: 2px solid #000; }
.grid th, .grid td {
  border: 1px solid #000; text-align: center; vertical-align: middle;
  font-size: 13px; line-height: 1.4; padding: 3px 6px;
}
.grid th { font-weight: normal; }
.grid tr.total td { font-weight: bold; }
@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; }
}
</style>
