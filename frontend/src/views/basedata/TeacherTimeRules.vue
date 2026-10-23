<script setup lang="ts">
import { NAlert, NButton, NSpace, NSpin, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  RULE_TYPE_LABELS, getTimeRuleConflicts, getTimeRules, replaceTimeRules,
} from '@/api/basedata'
import type { TeacherRuleType, TimeRuleConflict } from '@/api/basedata'
import { getAvailableSlots, getSemester } from '@/api/semesters'
import type { AvailableSlot } from '@/api/semesters'

const props = defineProps<{ teacherId: number; semesterId: number }>()
const emit = defineEmits<{ saved: [] }>()
const message = useMessage()

const loading = ref(true)
const saving = ref(false)
// 储存后:这位老师已经排在「不可排」时段的课(规则常在课表排好后才改,两边会矛盾)
const conflicts = ref<TimeRuleConflict[]>([])
const STATUS: Record<string, string> = { draft: '草稿', published: '已发布' }
const conflictGroups = computed(() => {
  const groups: { id: number; title: string; items: string[] }[] = []
  for (const c of conflicts.value) {
    let g = groups.find((x) => x.id === c.timetable_id)
    if (!g) {
      const status = STATUS[c.timetable_status] ?? c.timetable_status
      g = { id: c.timetable_id, title: `${c.timetable_name}(${status})`, items: [] }
      groups.push(g)
    }
    g.items.push(c.text)
  }
  return groups
})
const slots = ref<AvailableSlot[]>([])
const noTable = ref(false)
// (weekday_period_no) → 规则;无 key 表示无规则
const ruleMap = ref<Record<string, TeacherRuleType>>({})

const WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']
// 循环顺序:无 → 不可排 → 尽量避开 → 偏好 → 无
const CYCLE: (TeacherRuleType | null)[] = ['unavailable', 'avoid', 'prefer', null]
const COLORS: Record<TeacherRuleType, string> = {
  unavailable: '#ffcdd2',
  avoid: '#ffe0b2',
  prefer: '#c8e6c9',
}

const weekdays = computed(() => [...new Set(slots.value.map((s) => s.weekday))].sort((a, b) => a - b))
const rows = computed(() => {
  const map = new Map<number, string>()
  for (const s of slots.value) if (!map.has(s.period_no)) map.set(s.period_no, s.name)
  return [...map.entries()].sort((a, b) => a[0] - b[0]).map(([period_no, name]) => ({ period_no, name }))
})

function key(weekday: number, period_no: number) {
  return `${weekday}_${period_no}`
}
function cellExists(weekday: number, period_no: number) {
  return slots.value.some((s) => s.weekday === weekday && s.period_no === period_no)
}
function cycle(weekday: number, period_no: number) {
  if (!cellExists(weekday, period_no)) return
  const k = key(weekday, period_no)
  const current = ruleMap.value[k] ?? null
  const idx = CYCLE.indexOf(current)
  const next = CYCLE[(idx + 1) % CYCLE.length]
  if (next === null) delete ruleMap.value[k]
  else ruleMap.value[k] = next
}

onMounted(async () => {
  loading.value = true
  try {
    const sem = await getSemester(props.semesterId)
    const table = sem.period_tables.find((t) => t.is_default) ?? sem.period_tables[0]
    if (!table) {
      noTable.value = true
      return
    }
    slots.value = await getAvailableSlots(table.id)
    const rules = await getTimeRules(props.teacherId)
    for (const r of rules) ruleMap.value[key(r.weekday, r.period_no)] = r.rule_type
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  try {
    const rules = Object.entries(ruleMap.value).map(([k, rule_type]) => {
      const [weekday, period_no] = k.split('_').map(Number)
      return { weekday, period_no, rule_type }
    })
    await replaceTimeRules(props.teacherId, rules)
    message.success('时段规则已储存')
    // 规则已经存好了;查冲突只是提醒,查不到(例如网路问题)不该让用户以为没存成功
    conflicts.value = await getTimeRuleConflicts(props.teacherId).catch(() => [])
    if (conflicts.value.length === 0) emit('saved')
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <n-spin :show="loading">
    <n-space vertical>
      <n-text v-if="noTable" depth="3">
        此学期尚未建立节次表,请先于「学期与节次表」建立默认节次表后再设置时段规则。
      </n-text>
      <template v-else>
        <n-space size="small" align="center">
          <n-text depth="3">点格循环:</n-text>
          <span class="legend" :style="{ background: COLORS.unavailable }">不可排</span>
          <span class="legend" :style="{ background: COLORS.avoid }">尽量避开</span>
          <span class="legend" :style="{ background: COLORS.prefer }">偏好</span>
        </n-space>
        <div style="overflow-x: auto">
          <table class="rule-grid">
            <thead>
              <tr>
                <th>节次</th>
                <th v-for="wd in weekdays" :key="wd">周{{ WEEKDAY_NAMES[wd - 1] }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.period_no">
                <td class="rowhead">{{ row.name }}</td>
                <td
                  v-for="wd in weekdays"
                  :key="wd"
                  class="cell"
                  :class="{ disabled: !cellExists(wd, row.period_no) }"
                  :style="{ background: ruleMap[`${wd}_${row.period_no}`] ? COLORS[ruleMap[`${wd}_${row.period_no}`]] : '' }"
                  @click="cycle(wd, row.period_no)"
                >
                  {{ ruleMap[`${wd}_${row.period_no}`] ? RULE_TYPE_LABELS[ruleMap[`${wd}_${row.period_no}`]] : '' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <n-alert
          v-if="conflicts.length" type="warning" :show-icon="true"
          title="规则已储存,但目前课表有课排在「不可排」时段" data-testid="tr-conflicts"
        >
          <div v-for="g in conflictGroups" :key="g.id" class="conflict-group">
            <b>{{ g.title }}</b>
            <ul>
              <li v-for="(t, k) in g.items" :key="k" data-testid="tr-conflict">{{ t }}</li>
            </ul>
          </div>
          系统不会自动调动这些课;请到「排课工作台」调整,或回来修改规则。
        </n-alert>
        <n-space justify="end">
          <n-button v-if="conflicts.length" data-testid="tr-close" @click="emit('saved')">
            知道了
          </n-button>
          <n-button type="primary" :loading="saving" data-testid="tr-save" @click="save">
            储存规则
          </n-button>
        </n-space>
      </template>
    </n-space>
  </n-spin>
</template>

<style scoped>
.conflict-group ul { margin: 2px 0 6px; padding-left: 20px; }
.rule-grid { border-collapse: collapse; }
.rule-grid th, .rule-grid td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: center; min-width: 64px; }
.rule-grid th { background: rgba(128,128,128,0.08); }
.rowhead { white-space: nowrap; font-weight: 600; }
.cell { cursor: pointer; user-select: none; height: 34px; }
.cell.disabled { background: repeating-linear-gradient(45deg, #f5f5f5, #f5f5f5 4px, #eee 4px, #eee 8px); cursor: not-allowed; }
.legend { padding: 2px 8px; border-radius: 4px; font-size: 12px; color: #333; }
</style>
