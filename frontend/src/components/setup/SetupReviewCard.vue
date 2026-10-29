<script setup lang="ts">
import { NButton, NEmpty, NSpace, NText } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listAssignments } from '@/api/assignments'
import { listClassUnits, listRooms, listSubjects, listTeachers } from '@/api/basedata'
import { getSemester } from '@/api/semesters'
import { listTimetables } from '@/api/timetables'

const props = defineProps<{ semesterId: number | null }>()
const router = useRouter()

const counts = ref({ teachers: 0, classes: 0, subjects: 0, rooms: 0, assignments: 0, drafts: 0 })
const semesterLabel = ref('')
const defaultTable = ref('')
async function reload() {
  if (!props.semesterId) return
  const [ts, cs, ss, rs, as, ds, sem] = await Promise.all([
    listTeachers(props.semesterId), listClassUnits(props.semesterId),
    listSubjects(props.semesterId), listRooms(props.semesterId),
    listAssignments(props.semesterId), listTimetables(props.semesterId),
    getSemester(props.semesterId),
  ])
  counts.value = {
    teachers: ts.length, classes: cs.length, subjects: ss.length,
    rooms: rs.length, assignments: as.length, drafts: ds.length,
  }
  semesterLabel.value = sem.label
  defaultTable.value = sem.period_tables.find((t) => t.is_default)?.name
    ?? sem.period_tables[0]?.name ?? '未设'
}
watch(() => props.semesterId, reload)
onMounted(reload)

const gaps = computed(() => {
  const g: string[] = []
  if (!counts.value.teachers) g.push('还没有教师')
  if (!counts.value.classes) g.push('还没有班级')
  if (!counts.value.subjects) g.push('还没有科目')
  if (!counts.value.rooms) g.push('还没有场地')
  if (!counts.value.assignments) g.push('还没有配课（去排课中心做）')
  return g
})
function goScheduling() {
  void router.push({ name: 'scheduling-center' })
}
function goSystem() {
  void router.push({ name: 'system' })
}
</script>

<template>
  <div>
    <n-empty v-if="!semesterId" description="请先在上面建立或选择学期" style="padding: 12px 0" />
    <template v-else>
      <n-space :wrap="true" style="margin-bottom: 8px">
        <span class="ios-chip">{{ semesterLabel }}</span>
        <span class="ios-chip-gray ios-chip">默认节次表：{{ defaultTable }}</span>
        <span class="ios-chip-gray ios-chip">教师 {{ counts.teachers }} 人</span>
        <span class="ios-chip-gray ios-chip">班级 {{ counts.classes }} 个</span>
        <span class="ios-chip-gray ios-chip">科目 {{ counts.subjects }} 个</span>
        <span class="ios-chip-gray ios-chip">场地 {{ counts.rooms }} 间</span>
        <span class="ios-chip-gray ios-chip">配课 {{ counts.assignments }} 笔</span>
        <span class="ios-chip-gray ios-chip">课表 {{ counts.drafts }} 份</span>
      </n-space>
      <n-text v-if="gaps.length" type="warning" style="font-size: 13px">
        还缺：{{ gaps.join('、') }}
      </n-text>
      <n-text v-else type="success" style="font-size: 13px">
        资料齐了，可以去排课了 🎉
      </n-text>
      <n-space style="margin-top: 8px">
        <n-button size="small" type="primary" round @click="goScheduling">
          去排课中心
        </n-button>
        <n-button size="small" round @click="goSystem">
          去系统设置
        </n-button>
        <n-button size="small" text @click="reload">
          刷新
        </n-button>
      </n-space>
    </template>
  </div>
</template>
