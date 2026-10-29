<script setup lang="ts">
// 教学课时统计(管理员/主任/组长):查每个老师实际上了几节课,可筛教师与年级,
// 时间可按本周、一学期或自选日期;结果可按年级打印。
// 口径:已发布课表按日期展开、叠加请假调代课、未来日期不计入「已上」。
import {
  NButton, NDatePicker, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listClassUnits, listTeachers } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import { gradeLabel } from '@/api/substitutionLog'
import { getTeachingHours } from '@/api/teachingHours'
import type { HoursScope, TeachingHoursReport } from '@/api/teachingHours'

const router = useRouter()

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const teacherOptions = ref<{ label: string; value: number }[]>([])
const teacherId = ref<number | null>(null)
const gradeOptions = ref<{ label: string; value: number }[]>([])
const grade = ref<number | null>(null)
const scope = ref<HoursScope>('week')
const fromTs = ref<number | null>(null)
const toTs = ref<number | null>(null)
const report = ref<TeachingHoursReport | null>(null)
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const scopeLabel = computed(() =>
  scope.value === 'week' ? '本周' : scope.value === 'semester' ? '一学期' : '自选日期')

function toISO(ts: number | null): string | null {
  if (ts == null) return null
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 结果里出现过的年级(由小到大),作为各年级课时栏位。 */
const resultGrades = computed(() => {
  const s = new Set<number>()
  for (const t of report.value?.teachers ?? []) {
    for (const g of Object.keys(t.by_grade)) s.add(Number(g))
  }
  return [...s].sort((a, b) => a - b)
})

async function reload() {
  if (sid.value === null) return
  if (scope.value === 'custom' && (fromTs.value == null || toTs.value == null)) return
  loading.value = true
  try {
    report.value = await getTeachingHours({
      semester_id: sid.value, scope: scope.value,
      date_from: scope.value === 'custom' ? toISO(fromTs.value) : null,
      date_to: scope.value === 'custom' ? toISO(toTs.value) : null,
      teacher_id: teacherId.value, grade: grade.value,
    })
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  const [teachers, classes] = await Promise.all([listTeachers(id), listClassUnits(id)])
  teacherOptions.value = teachers.map((t) => ({ label: t.name, value: t.id }))
  gradeOptions.value = [...new Set(classes.map((c) => c.grade))].sort((a, b) => a - b)
    .map((g) => ({ label: gradeLabel(g), value: g }))
  teacherId.value = null
  grade.value = null
  await reload()
}

function onPrint() {
  if (sid.value === null) return
  const query: Record<string, string> = {
    semester_id: String(sid.value), scope: scope.value,
  }
  if (scope.value === 'custom') {
    query.date_from = toISO(fromTs.value) ?? ''
    query.date_to = toISO(toTs.value) ?? ''
  }
  if (teacherId.value) query.teacher_id = String(teacherId.value)
  if (grade.value) query.grade = String(grade.value)
  router.push({ name: 'teaching-hours-print', query })
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (!semesters.value.length) return
  await onSemesterChange(semesters.value[0].id)
})
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">教学课时统计</h1>

    <n-space align="center" :wrap="true">
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="选择学期" @update:value="onSemesterChange"
      />
      <n-select
        v-model:value="teacherId" :options="teacherOptions" clearable filterable
        placeholder="全部教师" style="width: 180px" data-testid="hours-teacher"
      />
      <n-select
        v-model:value="grade" :options="gradeOptions" clearable
        placeholder="全部年级" style="width: 140px" data-testid="hours-grade"
      />
      <n-radio-group v-model:value="scope" size="small" data-testid="hours-scope">
        <n-radio-button value="week">本周</n-radio-button>
        <n-radio-button value="semester">一学期</n-radio-button>
        <n-radio-button value="custom">自选日期</n-radio-button>
      </n-radio-group>
      <n-space v-if="scope === 'custom'" align="center">
        <n-date-picker v-model:value="fromTs" type="date" style="width: 150px" data-testid="hours-from" />
        <n-text depth="3">至</n-text>
        <n-date-picker v-model:value="toTs" type="date" style="width: 150px" data-testid="hours-to" />
      </n-space>
      <n-button type="primary" data-testid="hours-query" :loading="loading" @click="reload">查询</n-button>
      <n-button v-if="report" data-testid="hours-print" @click="onPrint">打印</n-button>
    </n-space>

    <n-space v-if="report" align="center">
      <n-text depth="3">
        {{ scopeLabel }} · 实际统计期间 {{ report.effective_from }} ~ {{ report.effective_to }}
        （未来日期不计入已上课时）
      </n-text>
      <n-tag type="info" data-testid="hours-total">合计 {{ report.total_periods }} 节</n-tag>
    </n-space>

    <table v-if="report?.teachers.length" class="ios-table" data-testid="hours-table">
      <thead>
        <tr>
          <th>教师</th>
          <th>总课时（节）</th>
          <th v-for="g in resultGrades" :key="g">{{ gradeLabel(g) }}（节）</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in report.teachers" :key="t.teacher_id">
          <td>{{ t.teacher_name }}</td>
          <td>{{ t.total }}</td>
          <td v-for="g in resultGrades" :key="g">{{ t.by_grade[String(g)] ?? 0 }}</td>
        </tr>
        <tr>
          <td><strong>合计</strong></td>
          <td><strong>{{ report.total_periods }}</strong></td>
          <td v-for="g in resultGrades" :key="g">
            <strong>{{ report.teachers.reduce((n, t) => n + (t.by_grade[String(g)] ?? 0), 0) }}</strong>
          </td>
        </tr>
      </tbody>
    </table>
    <n-empty v-else-if="report && !loading" description="该范围内没有已上课时（可能尚无已发布课表）" />
  </div>
</template>
