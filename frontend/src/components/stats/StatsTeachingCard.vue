<script setup lang="ts">
import { NButton, NDatePicker, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { listClassUnits, listTeachers } from '@/api/basedata'
import { getTeachingHours } from '@/api/teachingHours'
import type { HoursScope, TeachingHoursReport } from '@/api/teachingHours'

const props = defineProps<{ semesterId: number | null }>()

const scope = ref<HoursScope>('week')
const range = ref<[number, number] | null>(null)
const teacherId = ref<number | null>(null)
const grade = ref<number | null>(null)
const teachers = ref<{ label: string; value: number }[]>([])
const grades = ref<{ label: string; value: number }[]>([])
const report = ref<TeachingHoursReport | null>(null)

function fmtDate(ts: number): string {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
async function reload() {
  if (!props.semesterId) {
    report.value = null
    return
  }
  teachers.value = (await listTeachers(props.semesterId))
    .filter((t) => t.is_active).map((t) => ({ label: t.name, value: t.id }))
  const classes = await listClassUnits(props.semesterId)
  grades.value = [...new Set(classes.map((c) => c.grade))].sort((a, b) => a - b)
    .map((g) => ({ label: `${g}年级`, value: g }))
  report.value = await getTeachingHours({
    semester_id: props.semesterId, scope: scope.value,
    date_from: scope.value === 'custom' && range.value ? fmtDate(range.value[0]) : null,
    date_to: scope.value === 'custom' && range.value ? fmtDate(range.value[1]) : null,
    teacher_id: teacherId.value, grade: grade.value,
  })
}
watch(() => props.semesterId, reload)
onMounted(reload)
const byGradeText = computed(() => (r: Record<string, number>) =>
  Object.entries(r).map(([g, n]) => `${g}年级 ${n} 节`).join('、'))
</script>

<template>
  <div>
    <div class="ios-row-sub" style="margin-bottom: 8px">
      口径：已发布课表按日期展开，叠加请假调代课；未来日期不计入「已上」。
    </div>
    <n-space align="center" :wrap="true" style="margin-bottom: 12px">
      <n-radio-group v-model:value="scope" @update:value="reload">
        <n-radio-button value="week">
          本周
        </n-radio-button>
        <n-radio-button value="semester">
          本学期
        </n-radio-button>
        <n-radio-button value="custom">
          自选日期
        </n-radio-button>
      </n-radio-group>
      <n-date-picker
        v-if="scope === 'custom'" v-model:value="range" type="daterange"
        style="width: 260px" @update:value="reload"
      />
      <n-select
        v-model:value="teacherId" :options="teachers"
        placeholder="老师（空=全部）" style="width: 160px" filterable clearable @update:value="reload"
      />
      <n-select
        v-model:value="grade" :options="grades"
        placeholder="年级（空=全部）" style="width: 130px" clearable @update:value="reload"
      />
      <n-button size="small" text type="primary" @click="reload">
        刷新
      </n-button>
    </n-space>
    <n-empty v-if="!report || !report.teachers.length" description="该范围内没有实际上课纪录" style="padding: 12px 0" />
    <template v-else>
      <div class="ios-row-sub" style="margin-bottom: 8px">
        {{ report.effective_from }} ~ {{ report.effective_to }} · 合计 {{ report.total_periods }} 节
      </div>
      <table class="ios-table">
        <thead>
          <tr><th>老师</th><th>已上节数</th><th>分年级</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in report.teachers" :key="t.teacher_id">
            <td>{{ t.teacher_name }}</td>
            <td>{{ t.total }}</td>
            <td>{{ byGradeText(t.by_grade) || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
