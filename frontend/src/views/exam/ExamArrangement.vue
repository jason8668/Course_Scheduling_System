<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NInputNumber, NModal, NPopconfirm, NRadio, NRadioGroup,
  NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  ARRANGEMENT_LOCKED_HINT, ARRANGEMENT_MODE_LABELS, ARRANGEMENT_MODES,
  addExamRooms, arrangeExam, canEditArrangement, deleteExamRoom, exportArrangements,
  getArrangementLock, getArrangementRule, getExam, getSeatMap, listArrangements,
  listExamRooms, lockArrangement, moveArrangement, saveArrangementRule, swapArrangements,
  unlockArrangement,
} from '@/api/exam'
import type {
  ArrangementItem, ArrangementMode, ArrangementRule, ExamDetail, ExamRoom, SeatMap,
} from '@/api/exam'
import { ROOM_TYPE_LABELS, listRooms } from '@/api/basedata'
import type { Room } from '@/api/basedata'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 考场编排是教务职责:写操作只限 admin/director,越权时后端回 403,前端原样展示。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const exam = ref<ExamDetail | null>(null)
const loading = ref(false)
const forbidden = ref(false)

const rooms = ref<ExamRoom[]>([])
const availableRooms = ref<Room[]>([])
const rule = ref<ArrangementRule | null>(null)
const ruleForm = ref({ mode: 's_shape' as ArrangementMode, scatter_same_class: false, max_per_room: null as number | null })
const lock = ref({ locked: false, locked_by: null as string | null, locked_at: null as string | null })
// 锁定后自动编排与手动调整都被后端拒绝(409):相关按钮置灰并提示。
const editable = computed(() => canManage.value && canEditArrangement(lock.value.locked))

const arrangements = ref<ArrangementItem[]>([])
const seatMap = ref<SeatMap | null>(null)
const filterSubjectId = ref<number | null>(null)
const subjectOptions = computed(() => (exam.value?.subjects ?? []).map((s) => ({
  label: s.subject_name, value: s.subject_id,
})))

const warnings = ref<string[]>([])
const arrangeResult = ref<{ assigned: number; rooms_used: number } | null>(null)
const arranging = ref(false)

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}

async function reloadRooms() {
  try {
    rooms.value = (await listExamRooms(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '考场加载失败')
  }
}

async function reloadRule() {
  try {
    rule.value = await getArrangementRule(examId)
    ruleForm.value = {
      mode: (rule.value.mode as ArrangementMode) || 's_shape',
      scatter_same_class: rule.value.scatter_same_class,
      max_per_room: rule.value.max_per_room,
    }
  } catch (e) {
    message.error((e as ApiError).detail || '编排规则加载失败')
  }
}

async function reloadLock() {
  try {
    const res = await getArrangementLock(examId)
    lock.value = { locked: res.locked, locked_by: res.locked_by ?? null, locked_at: res.locked_at ?? null }
  } catch (e) {
    message.error((e as ApiError).detail || '锁定状态加载失败')
  }
}

async function reloadArrangements() {
  try {
    arrangements.value = (await listArrangements(examId, {
      subjectId: filterSubjectId.value,
    })).items
  } catch (e) {
    message.error((e as ApiError).detail || '编排结果加载失败')
  }
}

async function reloadSeatMap() {
  try {
    seatMap.value = await getSeatMap(examId, filterSubjectId.value)
  } catch (e) {
    message.error((e as ApiError).detail || '座位表加载失败')
  }
}

async function reload() {
  loading.value = true
  forbidden.value = false
  try {
    exam.value = await getExam(examId)
    availableRooms.value = await listRooms(exam.value.semester_id)
    await Promise.all([reloadRooms(), reloadRule(), reloadLock(), reloadArrangements(), reloadSeatMap()])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reload() })

async function onSubjectFilterChange() {
  await Promise.all([reloadArrangements(), reloadSeatMap()])
}

// ── 考场设置(KW-15):教室复用排课系统教室数据,设人数上限、类型、特殊考场标记 ──
// 考场类型只有普通/特殊(后端只认这两个值);不要复用排课教室的
// ROOM_TYPE_LABELS(普通教室/专科教室/实习工场/户外),那套值后端会 400。
const roomTypeOptions = [
  { label: '普通', value: '普通' },
  { label: '特殊', value: '特殊' },
]
const addableRooms = computed(() =>
  availableRooms.value
    .filter((r) => !rooms.value.some((x) => x.room_id === r.id))
    .map((r) => ({ label: `${r.name}${r.capacity ? `(${r.capacity} 人)` : ''}`, value: r.id })),
)
const roomForm = ref({ room_ids: [] as number[], capacity: null as number | null, room_type: '普通', is_special: false })
function onRoomsPick() {
  const ids = roomForm.value.room_ids
  if (ids.length === 1) {
    // 只选一间时回填该教室的容量,仍可手动改。
    const r = availableRooms.value.find((x) => x.id === ids[0])
    roomForm.value.capacity = r?.capacity ?? null
  } else if (ids.length > 1) {
    // 多选时人数上限留空则各用各的容量:把单选时自动回填的值清掉,
    // 避免误把第一间的容量用到全部;手动填了则对所选全部生效。
    roomForm.value.capacity = null
  }
}
function selectAllRooms() {
  roomForm.value.room_ids = addableRooms.value.map((r) => r.value)
  roomForm.value.capacity = null
}
async function saveRoom() {
  if (!exam.value) return
  if (!roomForm.value.room_ids.length) { message.warning('请选择教室'); return }
  try {
    const res = await addExamRooms(exam.value.id, {
      room_ids: roomForm.value.room_ids,
      capacity: roomForm.value.capacity,
      room_type: roomForm.value.room_type,
      is_special: roomForm.value.is_special,
    })
    roomForm.value = { room_ids: [], capacity: null, room_type: '普通', is_special: false }
    message.success(res.skipped > 0
      ? `已添加 ${res.created} 间考场,跳过 ${res.skipped} 间(已添加过)`
      : `已添加 ${res.created} 间考场`)
    await reloadRooms()
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '添加失败')
  }
}
async function removeRoom(r: ExamRoom) {
  if (!exam.value) return
  try {
    await deleteExamRoom(exam.value.id, r.id)
    message.success('考场已移除')
    await reloadRooms()
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '移除失败')
  }
}

// ── 编排规则(KW-16):三选一 + 打散开关 + 每场人数 ──
const modeOptions = ARRANGEMENT_MODES.map((m) => ({ label: ARRANGEMENT_MODE_LABELS[m], value: m }))
async function saveRule() {
  if (!exam.value) return
  try {
    rule.value = await saveArrangementRule(exam.value.id, {
      mode: ruleForm.value.mode,
      scatter_same_class: ruleForm.value.scatter_same_class,
      max_per_room: ruleForm.value.max_per_room,
    })
    message.success('编排规则已保存')
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '保存失败')
  }
}

// ── 自动编排(KW-17):一键编排,可选科目;warnings 原样展示,绝不改写或隐藏 ──
const arrangeSubjectId = ref<number | null>(null)
async function onArrange() {
  if (!exam.value) return
  arranging.value = true
  warnings.value = []
  arrangeResult.value = null
  try {
    const res = await arrangeExam(exam.value.id, arrangeSubjectId.value)
    // 后端返回的 warnings 全文原样展示,包括 S 型无成绩警告
    // “暂无上次成绩，暂按学号顺序编排”。
    warnings.value = res.warnings ?? []
    arrangeResult.value = { assigned: res.assigned, rooms_used: res.rooms_used }
    message.success(`已编排 ${res.assigned} 人,使用 ${res.rooms_used} 间考场`)
    await Promise.all([reloadArrangements(), reloadSeatMap()])
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '编排失败')
  } finally {
    arranging.value = false
  }
}

// ── 打印(KW-19~22):准考证、名单与签到表、门贴与桌贴、编排总表 ──
// 编排总表打印(KW-22 的 PDF 口径):跳到签到表页(按考场 + 科目出表,
// 即全年级编排总表的可打印形态),用户用浏览器“另存为 PDF”得到 PDF,
// 不做二进制 PDF 导出。
function goAdmissionTickets() {
  void router.push({ name: 'exam-exam-admission-tickets', params: { id: examId } })
}
function goAttendanceSheets() {
  void router.push({ name: 'exam-exam-attendance-sheets', params: { id: examId } })
}
function goDoorLabels() {
  void router.push({ name: 'exam-exam-door-labels', params: { id: examId } })
}

// ── 座位表与手工调整(KW-18):按考场分组,换考场与互换座位 ──
// 座位表行没有编排记录 id,按考场 + 学号在编排结果里找到对应记录再调换。
function findAssignment(roomId: number, studentNo: string): ArrangementItem | undefined {
  return arrangements.value.find((a) => a.room_id === roomId && a.student_no === studentNo)
}
const showMove = ref(false)
const moveTarget = ref<ArrangementItem | null>(null)
const moveForm = ref({ to_room_id: null as number | null, seat_no: null as number | null })
const roomOptions = computed(() =>
  rooms.value.map((r) => ({ label: r.room_name, value: r.room_id })),
)
function openMove(roomId: number, studentNo: string) {
  const a = findAssignment(roomId, studentNo)
  if (!a) { message.warning('找不到该考生的编排记录'); return }
  moveTarget.value = a
  moveForm.value = { to_room_id: null, seat_no: null }
  showMove.value = true
}
async function saveMove() {
  if (!exam.value || !moveTarget.value) return
  if (!moveForm.value.to_room_id) { message.warning('请选择目标考场'); return }
  try {
    await moveArrangement(exam.value.id, {
      assignment_id: moveTarget.value.id,
      to_room_id: moveForm.value.to_room_id,
      seat_no: moveForm.value.seat_no,
    })
    showMove.value = false
    message.success('已换考场')
    await Promise.all([reloadArrangements(), reloadSeatMap()])
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '换考场失败')
  }
}
const showSwap = ref(false)
const swapTarget = ref<ArrangementItem | null>(null)
const swapOtherId = ref<number | null>(null)
const swapOptions = computed(() =>
  arrangements.value
    .filter((a) => a.id !== swapTarget.value?.id)
    .map((a) => ({
      label: `${a.student_name}(${a.student_no}) ${a.room_name} ${a.seat_no ?? ''} 号`,
      value: a.id,
    })),
)
function openSwap(roomId: number, studentNo: string) {
  const a = findAssignment(roomId, studentNo)
  if (!a) { message.warning('找不到该考生的编排记录'); return }
  swapTarget.value = a
  swapOtherId.value = null
  showSwap.value = true
}
async function saveSwap() {
  if (!exam.value || !swapTarget.value) return
  if (!swapOtherId.value) { message.warning('请选择要互换的考生'); return }
  try {
    await swapArrangements(exam.value.id, {
      assignment_id_a: swapTarget.value.id,
      assignment_id_b: swapOtherId.value,
    })
    showSwap.value = false
    message.success('已互换座位')
    await Promise.all([reloadArrangements(), reloadSeatMap()])
  } catch (e) {
    if ((e as ApiError).status === 409) message.error(ARRANGEMENT_LOCKED_HINT)
    else message.error((e as ApiError).detail || '互换失败')
  }
}

// ── 导出(KW-22):下载考场安排表 Excel,前端不解析 ──
async function onExport() {
  if (!exam.value) return
  try {
    await exportArrangements(exam.value.id, filterSubjectId.value)
    message.success('考场安排表已开始下载')
  } catch (e) {
    message.error((e as ApiError).detail || '导出失败')
  }
}

// ── 锁定与解锁 ──
const lockNote = ref('')
async function onLock() {
  if (!exam.value) return
  try {
    const res = await lockArrangement(exam.value.id, lockNote.value.trim() || null)
    lock.value = { locked: res.locked, locked_by: res.locked_by ?? null, locked_at: res.locked_at ?? null }
    lockNote.value = ''
    message.success('考场编排已锁定')
  } catch (e) {
    message.error((e as ApiError).detail || '锁定失败')
  }
}
async function onUnlock() {
  if (!exam.value) return
  try {
    const res = await unlockArrangement(exam.value.id, lockNote.value.trim() || null)
    lock.value = { locked: res.locked, locked_by: res.locked_by ?? null, locked_at: res.locked_at ?? null }
    lockNote.value = ''
    message.success('考场编排已解锁')
  } catch (e) {
    message.error((e as ApiError).detail || '解锁失败')
  }
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ exam?.name ? `${exam.name} · 考场编排` : '考场编排' }}</h1>
    </div>

    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !exam" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="exam">
      <n-alert
        v-if="lock.locked" type="warning" style="margin-top: 16px"
        data-testid="arrangement-locked-hint"
      >
        {{ ARRANGEMENT_LOCKED_HINT }}(锁定人:{{ lock.locked_by ?? '—' }}<span v-if="lock.locked_at">,{{ lock.locked_at }}</span>)
      </n-alert>

      <!-- 考场设置(KW-15) -->
      <div class="ios-section">
        <div class="ios-section-title">考场设置</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            教室复用排课系统教室数据;每间考场设人数上限与类型,特殊考生考场打上特殊标记。
          </n-text>
          <n-empty v-if="rooms.length === 0" description="尚未设置考场,请先添加教室" />
          <div v-for="r in rooms" :key="r.id" class="ios-row">
            <div class="ios-row-main">
              <div class="ios-row-title">{{ r.room_name }}{{ r.is_special ? ' · 特殊考场' : '' }}</div>
              <div class="ios-row-sub">
                容量 {{ r.capacity ?? '—' }} 人{{ r.room_type ? ` · ${ROOM_TYPE_LABELS[r.room_type as keyof typeof ROOM_TYPE_LABELS] ?? r.room_type}` : '' }}
              </div>
            </div>
            <n-popconfirm v-if="editable" @positive-click="removeRoom(r)">
              <template #trigger><n-button size="small" text type="error">移除</n-button></template>
              确定移除该考场?
            </n-popconfirm>
          </div>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <n-select
              v-model:value="roomForm.room_ids" :options="addableRooms" clearable multiple
              max-tag-count="responsive" placeholder="选择教室(可多选)" style="width: 260px"
              :disabled="!editable" @update:value="onRoomsPick"
            />
            <n-button :disabled="!editable" @click="selectAllRooms">全选</n-button>
            <n-input-number
              v-model:value="roomForm.capacity" :min="1" placeholder="人数上限(留空用各教室容量)"
              style="width: 190px" :disabled="!editable"
            />
            <n-select
              v-model:value="roomForm.room_type" :options="roomTypeOptions"
              placeholder="类型" style="width: 130px" :disabled="!editable"
            />
            <n-space align="center" :wrap="false">
              <n-text style="font-size: 13px">特殊考场</n-text>
              <n-switch v-model:value="roomForm.is_special" :disabled="!editable" />
            </n-space>
            <n-button type="primary" :disabled="!editable" data-testid="arrange-add-room" @click="saveRoom">添加考场</n-button>
          </n-space>
        </div></div>
      </div>

      <!-- 编排规则(KW-16) -->
      <div class="ios-section">
        <div class="ios-section-title">编排规则</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            三选一,全年级统一执行;每考场人数上限与同班打散方式仍待学校确认。
          </n-text>
          <n-space vertical>
            <n-radio-group v-model:value="ruleForm.mode" :disabled="!editable">
              <n-space>
                <n-radio v-for="o in modeOptions" :key="o.value" :value="o.value">{{ o.label }}</n-radio>
              </n-space>
            </n-radio-group>
            <n-space align="center">
              <n-text style="font-size: 13px">同班学生座位打散</n-text>
              <n-switch v-model:value="ruleForm.scatter_same_class" :disabled="!editable" />
              <n-text style="font-size: 13px">每考场人数上限</n-text>
              <n-input-number
                v-model:value="ruleForm.max_per_room" :min="1" placeholder="不填则用考场容量"
                style="width: 160px" :disabled="!editable"
              />
            </n-space>
            <n-button type="primary" :disabled="!editable" data-testid="arrange-save-rule" @click="saveRule">保存编排规则</n-button>
          </n-space>
        </div></div>
      </div>

      <!-- 自动编排(KW-17) -->
      <div class="ios-section">
        <div class="ios-section-title">自动编排</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="arrangeSubjectId" :options="subjectOptions" clearable
              placeholder="全部科目" style="width: 160px" :disabled="!editable"
            />
            <n-button
              type="primary" :disabled="!editable" :loading="arranging"
              data-testid="arrange-run" @click="onArrange"
            >一键自动编排</n-button>
          </n-space>
          <n-alert
            v-if="arrangeResult" type="success" style="margin-top: 12px"
            data-testid="arrange-result"
          >
            已编排 {{ arrangeResult.assigned }} 人,使用 {{ arrangeResult.rooms_used }} 间考场。
          </n-alert>
          <!-- warnings 原样展示:后端返回什么文案就显示什么,不得改写、省略或合并 -->
          <n-alert
            v-if="warnings.length" type="warning" style="margin-top: 12px"
            data-testid="arrange-warnings"
          >
            <div v-for="(w, i) in warnings" :key="i">{{ w }}</div>
          </n-alert>
        </div></div>
      </div>

      <!-- 座位表(KW-20)与手工调整(KW-18) -->
      <div class="ios-section">
        <div class="ios-section-title">座位表</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="filterSubjectId" :options="subjectOptions" clearable
              placeholder="全部科目" style="width: 160px" @update:value="onSubjectFilterChange"
            />
            <n-button @click="onSubjectFilterChange">检索</n-button>
            <n-button data-testid="arrange-export" @click="onExport">导出考场安排表</n-button>
            <n-button data-testid="arrange-print-total" @click="goAttendanceSheets">打印编排总表</n-button>
            <n-button data-testid="arrange-print-tickets" @click="goAdmissionTickets">准考证打印</n-button>
            <n-button data-testid="arrange-print-attendance" @click="goAttendanceSheets">名单与签到表打印</n-button>
            <n-button data-testid="arrange-print-labels" @click="goDoorLabels">门贴与桌贴打印</n-button>
            <n-text depth="3" style="font-size: 12px">
              打印编排总表跳到名单与签到表页,用浏览器“另存为 PDF”得到 PDF。
            </n-text>
          </n-space>
          <n-empty v-if="!seatMap || seatMap.rooms.length === 0" description="暂无座位表,请先自动编排" style="margin-top: 12px" />
          <div v-for="room in seatMap?.rooms ?? []" :key="room.room_id" style="margin-top: 16px">
            <div class="ios-row-title" style="margin-bottom: 6px">{{ room.room_name }}(共 {{ room.seats.length }} 人)</div>
            <table class="ios-table">
              <thead><tr><th>座位号</th><th>学号</th><th>姓名</th><th>班级</th><th>备注</th><th /></tr></thead>
              <tbody>
                <tr v-for="s in room.seats" :key="`${room.room_id}-${s.seat_no}-${s.student_no}`">
                  <td>{{ s.seat_no ?? '—' }}</td>
                  <td>{{ s.student_no }}</td>
                  <td>{{ s.student_name }}</td>
                  <td>{{ s.class_name ?? '—' }}</td>
                  <td>{{ s.special_note ?? '—' }}</td>
                  <td>
                    <n-space size="small" :wrap="false">
                      <n-button
                        size="small" text type="primary" :disabled="!editable"
                        data-testid="arrange-move" @click="openMove(room.room_id, s.student_no)"
                      >换考场</n-button>
                      <n-button
                        size="small" text type="primary" :disabled="!editable"
                        data-testid="arrange-swap" @click="openSwap(room.room_id, s.student_no)"
                      >互换座位</n-button>
                    </n-space>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div></div>
      </div>

      <!-- 锁定与解锁 -->
      <div class="ios-section">
        <div class="ios-section-title">锁定与解锁</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            锁定后自动编排与手动调整都被拒绝,须先解锁才能再改;导出与查看不受锁定影响。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-input
              v-model:value="lockNote" placeholder="锁定/解锁备注(选填)" clearable
              style="width: 220px"
            />
            <n-button
              v-if="!lock.locked" type="warning" :disabled="!canManage"
              data-testid="arrange-lock" @click="onLock"
            >锁定编排</n-button>
            <n-button
              v-else type="primary" :disabled="!canManage"
              data-testid="arrange-unlock" @click="onUnlock"
            >解锁编排</n-button>
            <n-text depth="3" style="font-size: 13px">
              当前状态:{{ lock.locked ? '已锁定' : '未锁定' }}
            </n-text>
          </n-space>
        </div></div>
      </div>
    </template>

    <!-- 换考场 -->
    <n-modal v-model:show="showMove" preset="card" title="换考场" style="max-width: 480px">
      <n-space vertical>
        <n-text>考生:{{ moveTarget?.student_name }}({{ moveTarget?.student_no }}) {{ moveTarget?.room_name }} {{ moveTarget?.seat_no ?? '' }} 号</n-text>
        <n-text>目标考场</n-text>
        <n-select v-model:value="moveForm.to_room_id" :options="roomOptions" placeholder="选择目标考场" />
        <n-text>座位号(选填,不填由系统分配)</n-text>
        <n-input-number v-model:value="moveForm.seat_no" :min="1" placeholder="座位号" style="width: 160px" />
        <n-button type="primary" @click="saveMove">确认换考场</n-button>
      </n-space>
    </n-modal>

    <!-- 互换座位 -->
    <n-modal v-model:show="showSwap" preset="card" title="互换座位" style="max-width: 480px">
      <n-space vertical>
        <n-text>考生:{{ swapTarget?.student_name }}({{ swapTarget?.student_no }}) {{ swapTarget?.room_name }} {{ swapTarget?.seat_no ?? '' }} 号</n-text>
        <n-text>与以下考生互换</n-text>
        <n-select v-model:value="swapOtherId" :options="swapOptions" filterable placeholder="选择要互换的考生" />
        <n-button type="primary" @click="saveSwap">确认互换</n-button>
      </n-space>
    </n-modal>
  </div>
</template>
