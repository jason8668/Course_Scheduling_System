<script setup lang="ts">
import { NButton, NCollapse, NCollapseItem, NEmpty, NSelect, NSpace } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { listTeachers } from '@/api/basedata'
import { getStats } from '@/api/substitutionStats'
import type { MonthlyReport } from '@/api/substitutionStats'

const props = defineProps<{ semesterId: number | null }>()

const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const teacherId = ref<number | null>(null)
const teachers = ref<{ label: string; value: number }[]>([])
const report = ref<MonthlyReport | null>(null)

const yearOptions = computed(() => {
  const y = now.getFullYear()
  return [y - 1, y, y + 1].map((v) => ({ label: `${v} 年`, value: v }))
})
const monthOptions = Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1} 月`, value: i + 1 }))

async function reload() {
  if (!props.semesterId) {
    report.value = null
    return
  }
  teachers.value = (await listTeachers(props.semesterId))
    .filter((t) => t.is_active).map((t) => ({ label: t.name, value: t.id }))
  report.value = await getStats(props.semesterId, year.value, month.value, teacherId.value)
}
watch(() => props.semesterId, reload)
onMounted(reload)
</script>

<template>
  <div>
    <div class="ios-row-sub" style="margin-bottom: 8px">
      口径：按月结算。课时计费节数不含日薪；日薪另计天数（分担天单独列）；不计入课时的不算钱也不算节。
    </div>
    <n-space align="center" :wrap="true" style="margin-bottom: 12px">
      <n-select v-model:value="year" :options="yearOptions" style="width: 110px" @update:value="reload" />
      <n-select v-model:value="month" :options="monthOptions" style="width: 90px" @update:value="reload" />
      <n-select
        v-model:value="teacherId" :options="teachers"
        placeholder="老师（空=全部）" style="width: 160px" filterable clearable @update:value="reload"
      />
      <n-button size="small" text type="primary" @click="reload">
        刷新
      </n-button>
    </n-space>
    <n-empty v-if="!report || !report.summaries.length" description="该月没有代课纪录" style="padding: 12px 0" />
    <table v-else class="ios-table">
      <thead>
        <tr><th>老师</th><th>代课节数</th><th>计费节数</th><th>日薪天数</th><th>日薪共代节数</th><th>分担天数</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in report.summaries" :key="s.teacher_id">
          <td>{{ s.teacher_name }}</td>
          <td>{{ s.handled_count }}</td>
          <td>{{ s.billable_count }}</td>
          <td>{{ s.daily_days }}</td>
          <td>{{ s.daily_periods }}</td>
          <td>{{ s.daily_shared_days }}</td>
        </tr>
      </tbody>
    </table>
    <n-collapse v-if="report && report.details.length" style="margin-top: 8px">
      <n-collapse-item title="明细" name="details">
        <table class="ios-table">
          <thead>
            <tr><th>日期</th><th>节次</th><th>班级</th><th>科目</th><th>代课老师</th><th>请假老师</th><th>计费</th></tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in report.details" :key="i">
              <td>{{ d.date }}</td>
              <td>{{ d.period_name }}</td>
              <td>{{ d.class_names }}</td>
              <td>{{ d.subject_name }}</td>
              <td>{{ d.handler_name }}</td>
              <td>{{ d.absent_teacher_name }}</td>
              <td>{{ d.pay_kind === 'hourly' ? '课时' : d.pay_kind === 'daily' ? '日薪' : '不计' }}</td>
            </tr>
          </tbody>
        </table>
      </n-collapse-item>
    </n-collapse>
  </div>
</template>
