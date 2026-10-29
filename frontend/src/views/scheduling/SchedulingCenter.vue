<script setup lang="ts">
import {
  NAlert, NButton, NCollapse, NCollapseItem, NEmpty, NInput, NInputNumber, NModal, NPopconfirm,
  NRadioButton, NRadioGroup, NSelect, NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { classLabel } from '@/utils/labels'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { DragData, DropFeedback, GridEntry, PeriodCell } from '@/components/timetable/types'
import type { ApiError } from '@/api/client'
import {
  classLoad, createAlternate, createAssignment, createGroup, deleteAssignment, deleteGroup,
  listAlternates, listAssignments, listGroups, teacherLoad, updateAssignment,
} from '@/api/assignments'
import type {
  Assignment, AssignmentPayload, ClassLoad, SchedulingUnit, TeacherLoad, WeekParity,
} from '@/api/assignments'
import { listClassUnits, listRooms, listSubjects, listTeachers, ROOM_TYPE_LABELS } from '@/api/basedata'
import type { ClassUnit, Room, RoomType, Subject, Teacher } from '@/api/basedata'
import { getSemester, listSemesters } from '@/api/semesters'
import type { PeriodTable, SemesterListItem } from '@/api/semesters'
import {
  STATUS_LABELS, checkConflict, checkTimetable, conflictText, createTimetable, deleteEntry,
  deleteTimetable, duplicateTimetable, getClassPeriodTable, getPublishedTimetable, getTimetable,
  listTimetables, lockEntry, moveEntry, placeEntry, publishIssues, publishReport, publishTimetable,
  renameTimetable,
} from '@/api/timetables'
import type {
  CheckIssue, Completeness, PublishedTimetable, Timetable, TimetableBrief,
} from '@/api/timetables'
import {
  cancelSolveJob, getSolveJob, listRelaxable, listSolveJobs, preflight, startAutoSchedule,
  stopSolveJob,
} from '@/api/solver'
import type {
  ConflictReport, PreflightIssue, PreflightReport, RelaxableOption, SolveJob,
  UnscheduledCourse,
} from '@/api/solver'
import { gradeLabel } from '@/api/substitutionLog'

const message = useMessage()

// ── 共享学期上下文 ──
const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const assignments = ref<Assignment[]>([])
const classes = ref<ClassUnit[]>([])
const teachers = ref<Teacher[]>([])
const rooms = ref<Room[]>([])
const subjects = ref<Subject[]>([])
const groups = ref<SchedulingUnit[]>([])
const alternates = ref<SchedulingUnit[]>([])
const teacherLoads = ref<TeacherLoad[]>([])
const classLoads = ref<ClassLoad[]>([])
const allTables = ref<PeriodTable[]>([])
const defaultTable = ref<PeriodTable | null>(null)
const drafts = ref<TimetableBrief[]>([])
const ttId = ref<number | null>(null)
const tt = ref<Timetable | null>(null)
const periods = ref<PeriodCell[]>([])
const numWeekdays = ref(5)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const draftOptions = computed(() => drafts.value.map((d) => ({ label: d.name, value: d.id })))
const draftOnlyOptions = computed(() =>
  drafts.value.filter((d) => d.status === 'draft').map((d) => ({ label: d.name, value: d.id })))
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })))
const teacherOptions = computed(() =>
  teachers.value.filter((t) => t.is_active).map((t) => ({ label: t.name, value: t.id })))
const subjectOptions = computed(() =>
  subjects.value.map((s) => ({ label: s.name, value: s.id })))
const roomOptions = computed(() =>
  rooms.value.map((r) => ({ label: r.name, value: r.id })))
const roomTypeOptions = computed(() =>
  Object.entries(ROOM_TYPE_LABELS).map(([value, label]) => ({ label, value })))
const gradeOptions = computed(() =>
  [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
    .map((g) => ({ label: gradeLabel(g), value: g })))

async function refreshTimetable() {
  if (ttId.value) tt.value = await getTimetable(ttId.value)
}
async function loadPeriods() {
  let table: PeriodTable | null = defaultTable.value
  if (view.value === 'class' && classId.value) {
    try {
      table = await getClassPeriodTable(classId.value)
    } catch {
      table = defaultTable.value
    }
  }
  periods.value = (table?.periods ?? []) as PeriodCell[]
  numWeekdays.value = table?.num_weekdays ?? 5
}

async function loadSemester(id: number) {
  sid.value = id
  stopPolling()
  job.value = null
  const [sem, as, cs, ts, rs, ss, gs, alts, tl, cl] = await Promise.all([
    getSemester(id), listAssignments(id), listClassUnits(id), listTeachers(id), listRooms(id),
    listSubjects(id), listGroups(id), listAlternates(id), teacherLoad(id), classLoad(id),
  ])
  assignments.value = as
  classes.value = cs
  teachers.value = ts
  rooms.value = rs
  subjects.value = ss
  groups.value = gs
  alternates.value = alts
  teacherLoads.value = tl
  classLoads.value = cl
  allTables.value = sem.period_tables
  defaultTable.value = sem.period_tables.find((p) => p.is_default) ?? sem.period_tables[0] ?? null
  drafts.value = await listTimetables(id)
  if (drafts.value.length === 0) {
    const created = await createTimetable(id, '草稿A')
    drafts.value = await listTimetables(id)
    ttId.value = created.id
  } else {
    ttId.value = drafts.value[0].id
  }
  sourceId.value = drafts.value.find((d) => d.status === 'draft')?.id ?? null
  classId.value = cs[0]?.id ?? null
  teacherId.value = ts[0]?.id ?? null
  roomId.value = rs[0]?.id ?? null
  gradeFilter.value = null
  await refreshTimetable()
  await loadPeriods()
  check.value = await preflight(id).catch(() => null)
  history.value = await listSolveJobs(id).catch(() => [])
  relaxable.value = await listRelaxable().catch(() => [])
  const active = history.value.find(isActive)
  if (active) attachJob(active)
  published.value = await getPublishedTimetable(id).catch(() => null)
  resultClassId.value = published.value?.classes[0]?.id ?? null
  await loadResultPeriods()
}

async function reloadDrafts() {
  if (sid.value) drafts.value = await listTimetables(sid.value)
}
async function reloadAssignments() {
  if (!sid.value) return
  const [as, tl, cl] = await Promise.all(
    [listAssignments(sid.value), teacherLoad(sid.value), classLoad(sid.value)])
  assignments.value = as
  teacherLoads.value = tl
  classLoads.value = cl
}

// ── 手动排课(班级视角拖拉;教师/场地视角唯读)──
const view = ref<'class' | 'teacher' | 'room'>('class')
const classId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const roomId = ref<number | null>(null)
const gradeFilter = ref<number | null>(null)
const gradeFilterOptions = computed(() => {
  const grades = [...new Set(classes.value.map((c) => c.grade))].sort((a, b) => a - b)
  return grades.map((g) => ({ label: gradeLabel(g), value: g }))
})
const filteredClassOptions = computed(() =>
  classes.value
    .filter((c) => gradeFilter.value === null || c.grade === gradeFilter.value)
    .map((c) => ({ label: classLabel(c), value: c.id })))
const readonly = computed(() => view.value !== 'class')

function onGradeFilterChange() {
  if (view.value === 'class') {
    const first = classes.value.find(
      (c) => gradeFilter.value === null || c.grade === gradeFilter.value)
    classId.value = first?.id ?? null
    if (classId.value) void onClassChange(classId.value)
  }
}
async function onViewChange() {
  clearDrag()
  await loadPeriods()
}
async function onClassChange(id: number) {
  classId.value = id
  await loadPeriods()
}
async function onDraftChange(id: number) {
  ttId.value = id
  undoStack.value = []
  redoStack.value = []
  await refreshTimetable()
}

const shownEntries = computed(() => {
  const all = tt.value?.entries ?? []
  if (view.value === 'class') return classId.value ? all.filter((e) => e.class_ids.includes(classId.value!)) : []
  if (view.value === 'teacher') return teacherId.value ? all.filter((e) => e.teacher_ids.includes(teacherId.value!)) : []
  return roomId.value ? all.filter((e) => e.room_id === roomId.value) : []
})
const gridPeriods = computed<PeriodCell[]>(() => {
  if (view.value === 'class') return periods.value
  return [...periods.value, ...extraRows(
    shownEntries.value, classes.value, allTables.value, defaultTable.value) as PeriodCell[]]
})
function weekTag(p?: 'odd' | 'even' | null): '单' | '双' | undefined {
  return p === 'odd' ? '单' : p === 'even' ? '双' : undefined
}
const visibleEntries = computed<GridEntry[]>(() =>
  shownEntries.value.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: e.locked,
    subject: e.subject,
    teacher: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
    room: e.room ?? undefined,
    note: view.value === 'class' ? undefined
      : crossTableNote(e, classes.value, allTables.value, defaultTable.value),
    week: weekTag(e.week_parity),
  })))

const placedByAssignment = computed(() => {
  const m = new Map<number, number>()
  for (const e of tt.value?.entries ?? []) {
    m.set(e.course_assignment_id, (m.get(e.course_assignment_id) ?? 0) + e.span)
  }
  return m
})
interface TrayItem { a: Assignment; remaining: number; span: number; pair?: Assignment }
const trayItems = computed<TrayItem[]>(() => {
  if (view.value !== 'class' || !classId.value) return []
  const mine = assignments.value
    .filter((a) => a.scheduling_unit.classes.some((c) => c.id === classId.value))
  const items: TrayItem[] = []
  for (const a of mine) {
    if (a.week_parity === 'even' && mine.some(
      (o) => o.scheduling_unit.id === a.scheduling_unit.id && o.week_parity === 'odd')) continue
    const remaining = a.periods_per_week - (placedByAssignment.value.get(a.id) ?? 0)
    const b = a.block_rules[0]
    const span = b && remaining >= b.block_size ? b.block_size : 1
    const pair = a.week_parity === 'odd'
      ? mine.find((o) => o.scheduling_unit.id === a.scheduling_unit.id && o.week_parity === 'even')
      : undefined
    items.push({ a, remaining, span, pair })
  }
  return items.filter((x) => x.remaining > 0)
})
function trayTitle(item: TrayItem): string {
  if (item.a.week_parity && item.pair) return `单 ${item.a.subject.name}/双 ${item.pair.subject.name}`
  if (item.a.week_parity) return `${item.a.week_parity === 'odd' ? '单' : '双'} ${item.a.subject.name}`
  return item.a.subject.name
}
function trayTeachers(item: TrayItem): string {
  const names = (a: Assignment) => a.teachers.map((t) => t.name).join('、')
  return item.pair ? `${names(item.a)}/${names(item.pair)}` : names(item.a)
}
const totalRemaining = computed(() => trayItems.value.reduce((n, x) => n + x.remaining, 0))

interface WbDrag extends DragData { assignmentId: number; span: number }
const dragging = ref<WbDrag | null>(null)
const feedback = ref<DropFeedback | null>(null)
let lastKey = ''
let checkToken = 0
function clearDrag() {
  dragging.value = null
  feedback.value = null
  lastKey = ''
}
function onTrayDragStart(item: TrayItem, ev: DragEvent) {
  const data: WbDrag = { source: 'tray', assignmentId: item.a.id, span: item.span }
  dragging.value = data
  ev.dataTransfer?.setData('application/json', JSON.stringify(data))
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'move'
}
function onGridDragStart(data: DragData) {
  const e = tt.value?.entries.find((x) => x.id === data.entryId)
  if (!e) return
  dragging.value = { source: 'grid', entryId: e.id, assignmentId: e.course_assignment_id, span: e.span }
}
async function onCheck(p: { weekday: number; period_no: number }) {
  const d = dragging.value
  if (!d || !ttId.value) return
  const key = `${p.weekday}-${p.period_no}`
  if (key === lastKey) return
  lastKey = key
  const token = ++checkToken
  try {
    const res = await checkConflict(ttId.value, {
      course_assignment_id: d.assignmentId, weekday: p.weekday, period_no: p.period_no,
      span: d.span, ...(d.source === 'grid' ? { ignore_entry_id: d.entryId as number } : {}),
    })
    if (token !== checkToken) return
    feedback.value = {
      weekday: p.weekday, period_no: p.period_no,
      ok: res.ok, reason: res.conflicts[0]?.message,
    }
  } catch { /* 检查失败不阻挡 UI */ }
}
async function onDrop(p: { weekday: number; period_no: number }) {
  const d = dragging.value
  if (!d || !ttId.value) return
  const id = ttId.value
  clearDrag()
  try {
    if (d.source === 'tray') {
      const before = new Set((tt.value?.entries ?? []).map((e) => e.id))
      const updated = await placeEntry(id, {
        course_assignment_id: d.assignmentId, weekday: p.weekday,
        period_no: p.period_no, span: d.span,
      })
      tt.value = updated
      let createdId = updated.entries.find((e) => !before.has(e.id))?.id
      pushUndo({
        undo: async () => { if (createdId) await deleteEntry(id, createdId); await refreshTimetable() },
        redo: async () => {
          const before2 = new Set((tt.value?.entries ?? []).map((e) => e.id))
          const u = await placeEntry(id, {
            course_assignment_id: d.assignmentId, weekday: p.weekday,
            period_no: p.period_no, span: d.span,
          })
          tt.value = u
          createdId = u.entries.find((e) => !before2.has(e.id))?.id
        },
      })
    } else {
      const e = tt.value!.entries.find((x) => x.id === d.entryId)!
      const from = { weekday: e.weekday, period_no: e.period_no }
      const to = { weekday: p.weekday, period_no: p.period_no }
      tt.value = await moveEntry(id, e.id, to)
      pushUndo({
        undo: async () => { tt.value = await moveEntry(id, e.id, from) },
        redo: async () => { tt.value = await moveEntry(id, e.id, to) },
      })
    }
  } catch (err) {
    message.error(conflictText((err as ApiError).detail))
  }
}
async function onTrayDrop(ev: DragEvent) {
  ev.preventDefault()
  const d = dragging.value
  clearDrag()
  if (!d || d.source !== 'grid' || !ttId.value) return
  const id = ttId.value
  const e = tt.value?.entries.find((x) => x.id === d.entryId)
  if (!e) return
  if (e.locked) { message.warning('锁定格位不可移除,请先解锁'); return }
  const snap = { aid: e.course_assignment_id, weekday: e.weekday, period_no: e.period_no, span: e.span }
  let curId = e.id
  try {
    await deleteEntry(id, curId)
    await refreshTimetable()
    pushUndo({
      undo: async () => {
        const u = await placeEntry(id, {
          course_assignment_id: snap.aid, weekday: snap.weekday,
          period_no: snap.period_no, span: snap.span,
        })
        tt.value = u
        const back = u.entries.find(
          (x) => x.course_assignment_id === snap.aid && x.weekday === snap.weekday
            && x.period_no === snap.period_no)
        if (back) curId = back.id
      },
      redo: async () => { await deleteEntry(id, curId); await refreshTimetable() },
    })
  } catch (err) {
    message.error(conflictText((err as ApiError).detail))
  }
}
async function onSelect(g: GridEntry) {
  if (readonly.value || !ttId.value) return
  const id = ttId.value
  const e = tt.value?.entries.find((x) => x.id === g.id)
  if (!e) return
  const next = !e.locked
  tt.value = await lockEntry(id, e.id, next)
  message.info(next ? `已锁定「${e.subject}」` : `已解锁「${e.subject}」`)
  pushUndo({
    undo: async () => { tt.value = await lockEntry(id, e.id, !next) },
    redo: async () => { tt.value = await lockEntry(id, e.id, next) },
  })
}
interface Cmd { undo: () => Promise<void>; redo: () => Promise<void> }
const UNDO_LIMIT = 20
const undoStack = ref<Cmd[]>([])
const redoStack = ref<Cmd[]>([])
const busy = ref(false)
function pushUndo(c: Cmd) {
  undoStack.value.push(c)
  if (undoStack.value.length > UNDO_LIMIT) undoStack.value.shift()
  redoStack.value = []
}
async function doUndo() {
  const c = undoStack.value.pop()
  if (!c || busy.value) return
  busy.value = true
  try { await c.undo(); redoStack.value.push(c) } catch { message.error('复原失败') } finally { busy.value = false }
}
async function doRedo() {
  const c = redoStack.value.pop()
  if (!c || busy.value) return
  busy.value = true
  try { await c.redo(); undoStack.value.push(c) } catch { message.error('重做失败') } finally { busy.value = false }
}
function onKey(ev: KeyboardEvent) {
  if (!(ev.ctrlKey || ev.metaKey)) return
  const k = ev.key.toLowerCase()
  if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); void doUndo() }
  else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); void doRedo() }
}

// ── 配课 ──
interface AForm {
  target: 'single' | 'group' | 'alternate'
  class_id: number | null
  scheduling_unit_id: number | null
  subject_id: number | null
  teacher_ids: number[]
  lead_teacher_id: number | null
  periods_per_week: number
  block_rules: { block_size: number; count_per_week: number }[]
  required_room_type: RoomType | null
  room_id: number | null
  lock_room: boolean
  week_parity: WeekParity | null
}
function emptyForm(): AForm {
  return {
    target: 'single', class_id: null, scheduling_unit_id: null, subject_id: null,
    teacher_ids: [], lead_teacher_id: null, periods_per_week: 1, block_rules: [],
    required_room_type: null, room_id: null, lock_room: false, week_parity: null,
  }
}
const formShow = ref(false)
const editingId = ref<number | null>(null)
const form = ref<AForm>(emptyForm())
const onlySameGrade = ref(true)
const targetGrades = computed<number[]>(() => {
  if (form.value.target === 'single' && form.value.class_id) {
    const c = classes.value.find((x) => x.id === form.value.class_id)
    return c ? [c.grade] : []
  }
  const uid = form.value.scheduling_unit_id
  if (!uid) return []
  const u = (form.value.target === 'group' ? groups.value : alternates.value)
    .find((x) => x.id === uid)
  return u ? [...new Set(u.classes.map((c) => c.grade))] : []
})
const formTeacherOptions = computed(() => teachers.value.filter((t) => {
  if (!onlySameGrade.value) return true
  if (form.value.teacher_ids.includes(t.id)) return true
  if (!t.grade_ids?.length) return true
  if (!targetGrades.value.length) return true
  return t.grade_ids.some((g) => targetGrades.value.includes(g))
}).map((t) => ({ label: t.name, value: t.id })))
const leadOptions = computed(() => teachers.value
  .filter((t) => form.value.teacher_ids.includes(t.id))
  .map((t) => ({ label: t.name, value: t.id })))
const groupOptions = computed(() => groups.value.map((g) => ({ label: g.name, value: g.id })))
const alternateOptions = computed(() => alternates.value.map((g) => ({ label: g.name, value: g.id })))

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  formShow.value = true
}
function openCreateWeek(u: SchedulingUnit, week: WeekParity, from?: Assignment) {
  editingId.value = null
  form.value = {
    ...emptyForm(), target: 'alternate', scheduling_unit_id: u.id, week_parity: week,
    periods_per_week: from?.periods_per_week ?? 1,
    block_rules: from?.block_rules.map((b) => ({ ...b })) ?? [],
  }
  formShow.value = true
}
function openEdit(a: Assignment) {
  editingId.value = a.id
  const kind = a.scheduling_unit.unit_type
  const isGroup = kind !== 'single'
  form.value = {
    target: kind === 'alternate' ? 'alternate' : isGroup ? 'group' : 'single',
    week_parity: a.week_parity,
    class_id: isGroup ? null : (a.scheduling_unit.classes[0]?.id ?? null),
    scheduling_unit_id: isGroup ? a.scheduling_unit.id : null,
    subject_id: a.subject.id,
    teacher_ids: a.teachers.map((t) => t.teacher_id),
    lead_teacher_id: a.teachers.find((t) => t.is_lead)?.teacher_id ?? null,
    periods_per_week: a.periods_per_week,
    block_rules: a.block_rules.map((b) => ({ block_size: b.block_size, count_per_week: b.count_per_week })),
    required_room_type: a.required_room_type,
    room_id: a.room_id,
    lock_room: a.lock_room,
  }
  formShow.value = true
}
function addBlock() {
  form.value.block_rules.push({ block_size: 2, count_per_week: 1 })
}
function removeBlock(i: number) {
  form.value.block_rules.splice(i, 1)
}
async function saveAssignment() {
  const f = form.value
  if (f.target === 'single' && !f.class_id) return message.warning('请选择班级')
  if (f.target === 'group' && !f.scheduling_unit_id) return message.warning('请选择跑班群组')
  if (f.target === 'alternate' && !f.scheduling_unit_id) return message.warning('请选择单双周组')
  if (f.target === 'alternate' && !f.week_parity) return message.warning('请选择单周或双周')
  if (!f.subject_id) return message.warning('请选择科目')
  if (f.teacher_ids.length === 0) return message.warning('请至少指定一位教师')
  const lead = f.lead_teacher_id && f.teacher_ids.includes(f.lead_teacher_id)
    ? f.lead_teacher_id : f.teacher_ids[0]
  const payload: AssignmentPayload = {
    class_id: f.target === 'single' ? f.class_id : null,
    scheduling_unit_id: f.target === 'single' ? null : f.scheduling_unit_id,
    week_parity: f.target === 'alternate' ? f.week_parity : null,
    subject_id: f.subject_id,
    periods_per_week: f.periods_per_week,
    teachers: f.teacher_ids.map((id) => ({ teacher_id: id, is_lead: id === lead })),
    block_rules: f.block_rules,
    required_room_type: f.required_room_type || null,
    room_id: f.room_id,
    lock_room: f.lock_room,
  }
  try {
    if (editingId.value) await updateAssignment(editingId.value, payload)
    else await createAssignment(sid.value!, payload)
    formShow.value = false
    message.success('已储存配课')
    await reloadAssignments()
  } catch (e) {
    message.error((e as ApiError).detail || '储存失败')
  }
}
async function removeAssignment(a: Assignment) {
  await deleteAssignment(a.id)
  message.success('已删除')
  await reloadAssignments()
}
function weeksOf(u: SchedulingUnit): { odd?: Assignment; even?: Assignment } {
  const list = assignments.value.filter((a) => a.scheduling_unit.id === u.id)
  return {
    odd: list.find((a) => a.week_parity === 'odd'),
    even: list.find((a) => a.week_parity === 'even'),
  }
}

const groupShow = ref(false)
const groupForm = ref<{ name: string; class_ids: number[] }>({ name: '', class_ids: [] })
function openGroup() {
  groupForm.value = { name: '', class_ids: [] }
  groupShow.value = true
}
async function saveGroup() {
  if (!groupForm.value.name) return message.warning('请输入群组名称')
  if (groupForm.value.class_ids.length < 2) return message.warning('跑班群组至少需 2 个班级')
  try {
    await createGroup(sid.value!, groupForm.value)
    groupShow.value = false
    message.success('已建立跑班群组')
    await reloadAssignments()
    groups.value = await listGroups(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}
async function removeGroup(id: number) {
  await deleteGroup(id)
  message.success('已删除群组')
  groups.value = await listGroups(sid.value!)
  await reloadAssignments()
}
const altClassId = ref<number | null>(null)
async function createAlt() {
  if (!altClassId.value) return message.warning('请选择班级')
  try {
    await createAlternate(sid.value!, { class_id: altClassId.value })
    message.success('已建立单双周组')
    alternates.value = await listAlternates(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失败')
  }
}

// ── 自动排课 ──
const check = ref<PreflightReport | null>(null)
const job = ref<SolveJob | null>(null)
const history = ref<SolveJob[]>([])
const relaxable = ref<RelaxableOption[]>([])
const sourceId = ref<number | null>(null)
const minutes = ref(5)
const allowPartial = ref(false)
const relax = ref<string[]>([])
const scopeGrades = ref<number[]>([])
const starting = ref(false)
const blockingIssues = ref<PreflightIssue[]>([])
const POLL_MS = 2000
let timer: ReturnType<typeof setInterval> | null = null
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
const isActive = (j: SolveJob) => j.status === 'queued' || j.status === 'running'
const running = computed(() => !!job.value && isActive(job.value))
function jobLabel(j: SolveJob): string {
  if (isActive(j) && j.phase === 'explaining') return '定位无解原因中'
  return ({ queued: '排队中', running: '排课中', finished: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[j.status] ?? j.status
}
const conflict = computed<ConflictReport | null>(() => job.value?.conflict ?? null)
const unscheduled = computed<UnscheduledCourse[]>(() => job.value?.unscheduled ?? [])
const unplacedPeriods = computed(() => unscheduled.value.reduce((n, u) => n + u.periods, 0))
const elapsedText = computed(() => {
  const s = job.value?.elapsed ?? 0
  return s < 1 ? '不到 1 秒' : `${Math.round(s)} 秒`
})
function attachJob(j: SolveJob) {
  job.value = j
  stopPolling()
  if (isActive(j)) timer = setInterval(poll, POLL_MS)
}
function selectJob(j: SolveJob) {
  attachJob(j)
}
async function poll() {
  if (!job.value) return
  try {
    job.value = await getSolveJob(job.value.job_id)
  } catch {
    stopPolling()
    return
  }
  if (!running.value) {
    stopPolling()
    if (job.value.status === 'finished') message.success(`已产生「${job.value.result_name}」`)
    if (job.value.status === 'cancelled') message.info('已取消排课')
    if (job.value.status === 'failed') message.error(job.value.error ?? '排课失败')
    if (sid.value) {
      await reloadDrafts()
      check.value = await preflight(sid.value).catch(() => null)
      history.value = await listSolveJobs(sid.value).catch(() => [])
    }
  }
}
async function onStartAuto() {
  if (!sourceId.value) return
  starting.value = true
  blockingIssues.value = []
  try {
    const { job_id } = await startAutoSchedule(sourceId.value, minutes.value * 60, {
      allowPartial: allowPartial.value,
      relax: allowPartial.value ? relax.value : [],
      grades: scopeGrades.value.length ? scopeGrades.value : undefined,
    })
    attachJob(await getSolveJob(job_id))
    if (sid.value) history.value = await listSolveJobs(sid.value).catch(() => [])
  } catch (e) {
    const detail = (e as ApiError).detail as unknown
    if (detail && typeof detail === 'object' && 'issues' in detail) {
      blockingIssues.value = (detail as { issues: PreflightIssue[] }).issues
      message.error('资料未通过排课前置检查')
    } else {
      message.error((e as ApiError).message || '无法启动排课')
    }
  } finally {
    starting.value = false
  }
}
async function onRetryPartial() {
  allowPartial.value = true
  relax.value = conflict.value?.relaxable_codes ?? []
  job.value = null
  await onStartAuto()
}
async function onStopJob() {
  if (!job.value) return
  await stopSolveJob(job.value.job_id)
  message.info('已要求提前结束,将保留目前最佳解')
}
async function onCancelJob() {
  if (!job.value) return
  await cancelSolveJob(job.value.job_id)
  message.info('已要求取消')
}

// ── 版本与发布 ──
const renameShow = ref(false)
const renameTarget = ref<TimetableBrief | null>(null)
const renameValue = ref('')
function openRename(t: TimetableBrief) {
  renameTarget.value = t
  renameValue.value = t.name
  renameShow.value = true
}
async function onRename() {
  if (!renameTarget.value || !renameValue.value) return
  await renameTimetable(renameTarget.value.id, renameValue.value)
  renameShow.value = false
  message.success('已改名')
  await reloadDrafts()
}
async function onCreateDraft() {
  if (!sid.value) return
  const created = await createTimetable(sid.value, `草稿${String.fromCharCode(65 + drafts.value.length)}`)
  message.success('已建立草稿')
  await reloadDrafts()
  ttId.value = created.id
  undoStack.value = []
  redoStack.value = []
  await refreshTimetable()
}
async function onDuplicateDraft(t: TimetableBrief) {
  await duplicateTimetable(t.id, `${t.name} 复本`)
  message.success('已复制为新草稿')
  await reloadDrafts()
}
async function onDeleteDraft(id: number) {
  await deleteTimetable(id)
  message.success('已删除')
  await reloadDrafts()
  if (ttId.value === id) {
    ttId.value = drafts.value[0]?.id ?? null
    await refreshTimetable()
  }
}
const warnShow = ref(false)
const warnMode = ref<'publish' | 'check'>('publish')
const report = ref<Completeness | null>(null)
const issues = ref<CheckIssue[]>([])
const publishTarget = ref<TimetableBrief | null>(null)
const incomplete = computed(() => !!report.value && !report.value.complete)
const warnTitle = computed(() => {
  const name = publishTarget.value ? `「${publishTarget.value.name}」` : ''
  if (issues.value.length && incomplete.value) return `${name}课表有冲突,且尚有课务未排完`
  return issues.value.length ? `${name}课表有冲突` : `${name}尚有课务未排完`
})
const issueGroups = computed(() => {
  const groups: { label: string; items: CheckIssue[] }[] = []
  for (const i of issues.value) {
    const last = groups[groups.length - 1]
    if (last && last.label === i.label) last.items.push(i)
    else groups.push({ label: i.label, items: [i] })
  }
  return groups
})
function warnStale(n?: number) {
  if (n && n > 0) {
    message.warning(
      `有 ${n} 笔今日之后的调代课是依先前课表安排的,请至今日看板/调代课纪录重新查看`,
      { duration: 8000 })
  }
}
async function onPublish(t: TimetableBrief) {
  publishTarget.value = t
  try {
    const r = await publishTimetable(t.id)
    message.success(`已发布「${t.name}」`)
    warnStale(r.stale_affected)
    await reloadDrafts()
    if (sid.value) published.value = await getPublishedTimetable(sid.value).catch(() => null)
  } catch (e) {
    const r = publishReport((e as ApiError).detail)
    if (r) {
      report.value = r
      issues.value = publishIssues((e as ApiError).detail)
      warnMode.value = 'publish'
      warnShow.value = true
    } else {
      message.error((e as ApiError).detail as string || '发布失败')
    }
  }
}
async function onForcePublish() {
  if (!publishTarget.value) return
  try {
    const r = await publishTimetable(publishTarget.value.id, true)
    warnShow.value = false
    const left = [issues.value.length ? '冲突' : '', incomplete.value ? '未排完课务' : '']
      .filter(Boolean).join('与')
    message.success(`已强制发布(仍有${left})`)
    warnStale(r.stale_affected)
    await reloadDrafts()
    if (sid.value) published.value = await getPublishedTimetable(sid.value).catch(() => null)
  } catch (e) {
    message.error((e as ApiError).detail as string || '发布失败')
  }
}
const checkText = ref('')
const checkOk = ref(false)
async function onCheckDraft(t: TimetableBrief) {
  const r = await checkTimetable(t.id)
  const c = r.completeness
  const done = c.complete
    ? `课务已排完(${c.placed}/${c.required} 节)`
    : `尚有 ${c.remaining} 节未排(${c.placed}/${c.required})`
  const clash = r.issues.length ? `,有 ${r.issues.length} 项冲突` : ',没有冲突'
  checkText.value = `「${t.name}」${done}${clash}`
  checkOk.value = r.ok
  if (r.issues.length) {
    publishTarget.value = t
    report.value = c
    issues.value = r.issues
    warnMode.value = 'check'
    warnShow.value = true
  }
}
// ── 结果查看(已发布课表,唯读)──
const published = ref<PublishedTimetable | null>(null)
const resultClassId = ref<number | null>(null)
const resultPeriods = ref<PeriodCell[]>([])
async function loadResultPeriods() {
  let table: PeriodTable | null = defaultTable.value
  if (resultClassId.value) {
    try {
      table = await getClassPeriodTable(resultClassId.value)
    } catch {
      table = defaultTable.value
    }
  }
  resultPeriods.value = (table?.periods ?? []) as PeriodCell[]
}
const resultEntries = computed<GridEntry[]>(() => {
  if (!published.value || !resultClassId.value) return []
  return published.value.entries
    .filter((e) => e.class_ids.includes(resultClassId.value!))
    .map((e) => ({
      id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: e.locked,
      subject: e.subject, teacher: e.teachers.join('、'), room: e.room ?? undefined,
      week: weekTag(e.week_parity),
    }))
})
function openResult() {
  document.getElementById('sc-result')?.scrollIntoView({ behavior: 'smooth' })
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await loadSemester(semesters.value[0].id)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  stopPolling()
})
</script>

<template>
  <div class="ios-page" style="max-width: none">
    <h1 class="ios-title">
      排课中心
    </h1>
    <div class="ios-subtitle">
      配课 → 排课 → 发布，在一页里做完，学期只选一次
    </div>
    <n-space align="center" :wrap="true" style="margin-top: 16px">
      <n-select
        :value="sid" :options="semesterOptions" placeholder="选择学期"
        style="width: 220px" @update:value="loadSemester"
      />
      <span class="ios-chip-gray ios-chip">
        {{ assignments.length }} 笔配课 · {{ drafts.length }} 份课表
      </span>
    </n-space>

    <section class="ios-section">
      <div class="ios-section-title">
        <span>配课</span>
        <n-space>
          <n-button size="small" text type="primary" @click="openCreate">
            新增配课
          </n-button>
          <n-button size="small" text type="primary" @click="openGroup">
            新建跑班群组
          </n-button>
        </n-space>
      </div>
      <div class="ios-card">
        <n-empty v-if="!assignments.length" description="尚无配课，先新增配课" style="padding: 24px 0" />
        <template v-else>
          <div v-for="a in assignments" :key="a.id" class="ios-row">
            <div class="ios-row-main">
              <span class="ios-row-title">{{ a.scheduling_unit.name }} · {{ a.subject.name }}</span>
              <span class="ios-row-sub" style="margin-left: 8px">
                {{ a.teachers.map((t) => t.name).join('、') }} · 每周 {{ a.periods_per_week }} 节
              </span>
              <span v-if="a.week_parity" class="ios-chip" style="margin-left: 8px">
                {{ a.week_parity === 'odd' ? '单周' : '双周' }}
              </span>
              <span v-if="a.block_rules.length" class="ios-chip-gray ios-chip" style="margin-left: 4px">
                {{ a.block_rules.map((b) => `${b.block_size}连堂×${b.count_per_week}`).join('、') }}
              </span>
              <!-- 操作跟在标题信息后面,不再推到行尾:原来标题在左、按钮在右,
                   整行被 flex:1 撑满,中间一大片空白,看着像两截。 -->
              <span style="margin-left: 8px; white-space: nowrap">
                <n-button size="small" text type="primary" @click="openEdit(a)">
                  编辑
                </n-button>
                <n-popconfirm @positive-click="removeAssignment(a)">
                  <template #trigger>
                    <n-button size="small" text type="error" style="margin-left: 8px">
                      删除
                    </n-button>
                  </template>
                  确定删除这笔配课?
                </n-popconfirm>
              </span>
            </div>
          </div>
        </template>
        <div v-if="alternates.length" style="padding: 10px 16px; border-top: 1px solid rgba(0,0,0,0.06)">
          <div class="ios-row-sub" style="margin-bottom: 6px">
            单双周组（同一格隔周轮流）
          </div>
          <n-space vertical size="small">
            <n-space v-for="u in alternates" :key="u.id" align="center" :wrap="true">
              <n-text strong style="font-size: 14px">
                {{ u.name }}
              </n-text>
              <n-text depth="3" style="font-size: 13px">
                单周：{{ weeksOf(u).odd?.subject.name ?? '未排' }} · 双周：{{ weeksOf(u).even?.subject.name ?? '未排' }}
              </n-text>
              <n-button
                v-if="!weeksOf(u).odd" size="small" text type="primary"
                @click="openCreateWeek(u, 'odd', weeksOf(u).even)"
              >
                补单周
              </n-button>
              <n-button
                v-if="!weeksOf(u).even" size="small" text type="primary"
                @click="openCreateWeek(u, 'even', weeksOf(u).odd)"
              >
                补双周
              </n-button>
            </n-space>
          </n-space>
          <n-space align="center" style="margin-top: 8px">
            <n-select
              v-model:value="altClassId" :options="classOptions" placeholder="选一个班建单双周组"
              style="width: 200px" filterable
            />
            <n-button size="small" round @click="createAlt">
              建立单双周组
            </n-button>
          </n-space>
        </div>
        <div v-if="groups.length" style="padding: 10px 16px; border-top: 1px solid rgba(0,0,0,0.06)">
          <div class="ios-row-sub" style="margin-bottom: 6px">
            跑班群组
          </div>
          <n-space vertical size="small">
            <n-space v-for="g in groups" :key="g.id" align="center" :wrap="true">
              <n-text strong style="font-size: 14px">
                {{ g.name }}
              </n-text>
              <n-text depth="3" style="font-size: 13px">
                {{ g.classes.map((c) => c.name).join('、') }}
              </n-text>
              <n-popconfirm @positive-click="removeGroup(g.id)">
                <template #trigger>
                  <n-button size="small" text type="error">
                    删除
                  </n-button>
                </template>
                确定删除这个群组?其配课将一并受影响。
              </n-popconfirm>
            </n-space>
          </n-space>
        </div>
        <n-collapse style="padding: 0 16px 8px">
          <n-collapse-item title="教师 / 班级负荷" name="loads">
            <n-space vertical size="small">
              <div>
                <div class="ios-row-sub" style="margin-bottom: 4px">
                  教师
                </div>
                <n-space vertical size="small">
                  <n-text v-for="l in teacherLoads" :key="l.teacher_id" depth="2" style="font-size: 13px">
                    {{ l.name }}：已排 {{ l.assigned }} / 应授 {{ l.target }} 节
                    <span v-if="l.over_limit" class="ios-chip-warn ios-chip">超 {{ l.delta }} 节</span>
                  </n-text>
                </n-space>
              </div>
              <div>
                <div class="ios-row-sub" style="margin-bottom: 4px">
                  班级
                </div>
                <n-space vertical size="small">
                  <n-text v-for="l in classLoads" :key="l.class_id" depth="2" style="font-size: 13px">
                    {{ l.name }}：已排 {{ l.assigned }} / 容量 {{ l.capacity }} 节
                    <span v-if="l.over_capacity" class="ios-chip-warn ios-chip">超容量</span>
                  </n-text>
                </n-space>
              </div>
            </n-space>
          </n-collapse-item>
        </n-collapse>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 60ms">
      <div class="ios-section-title">
        <span>手动排课</span>
        <n-space>
          <n-select
            v-if="drafts.length" :value="ttId" :options="draftOptions"
            style="width: 140px" @update:value="onDraftChange"
          />
          <n-button size="small" text :disabled="!undoStack.length" @click="doUndo">
            复原 (Ctrl+Z)
          </n-button>
          <n-button size="small" text :disabled="!redoStack.length" @click="doRedo">
            重做
          </n-button>
        </n-space>
      </div>
      <n-alert v-if="!sid" type="info">
        请先建立学期并完成配课，再回此页排课。
      </n-alert>
      <template v-else>
        <n-space align="center" :wrap="true" style="margin-bottom: 12px">
          <n-radio-group :value="view" @update:value="(v: 'class'|'teacher'|'room') => { view = v; onViewChange() }">
            <n-radio-button value="class">
              班级视角
            </n-radio-button>
            <n-radio-button value="teacher">
              教师视角
            </n-radio-button>
            <n-radio-button value="room">
              场地视角
            </n-radio-button>
          </n-radio-group>
          <n-select
            v-if="view === 'class'" v-model:value="gradeFilter" :options="gradeFilterOptions"
            style="width: 130px" clearable
            placeholder="全部年级" @update:value="onGradeFilterChange"
          />
          <n-select
            v-if="view === 'class'" :value="classId"
            :options="filteredClassOptions" style="width: 180px" filterable @update:value="onClassChange"
          />
          <n-select
            v-else-if="view === 'teacher'" v-model:value="teacherId"
            :options="teacherOptions" style="width: 180px" filterable
          />
          <n-select
            v-else v-model:value="roomId"
            :options="roomOptions" style="width: 180px" filterable
          />
          <span v-if="readonly" class="ios-chip-warn ios-chip">唯读查看（排课请切回班级视角）</span>
          <span class="ios-row-sub">变更即时储存；点格内卡片可锁定 / 解锁</span>
        </n-space>
        <div class="wb-layout">
          <div class="ios-card" style="flex: 1; min-width: 0">
            <n-empty v-if="periods.length === 0" description="此学期尚无节次表" style="padding: 24px 0" />
            <TimetableGrid
              v-else
              :periods="gridPeriods" :num-weekdays="numWeekdays" :entries="visibleEntries"
              :dragging="dragging" :feedback="feedback" :readonly="readonly"
              @dragstart="onGridDragStart" @dragend="clearDrag"
              @check="onCheck" @drop="onDrop" @select="onSelect"
            />
          </div>
          <div
            v-if="!readonly" class="ios-card wb-tray"
            @dragover.prevent @drop="onTrayDrop"
          >
            <div class="ios-row">
              <span class="ios-row-title">未排课务</span>
              <span :class="totalRemaining === 0 ? 'ios-chip-green ios-chip' : 'ios-chip'">
                剩 {{ totalRemaining }} 节
              </span>
            </div>
            <div class="tray-list">
              <n-text v-if="trayItems.length === 0" depth="3">
                本班课务已全部排入 🎉
              </n-text>
              <div
                v-for="item in trayItems" :key="item.a.id"
                class="tray-item" draggable="true"
                @dragstart="onTrayDragStart(item, $event)" @dragend="clearDrag"
              >
                <div class="tray-subject">
                  {{ trayTitle(item) }}
                  <span v-if="item.a.week_parity" class="ios-chip">单双周</span>
                  <span v-if="item.span > 1" class="ios-chip-warn ios-chip">{{ item.span }}连堂</span>
                </div>
                <div class="tray-meta">
                  {{ trayTeachers(item) }} · 剩 {{ item.remaining }} 节
                </div>
              </div>
              <div class="ios-row-sub" style="margin-top: 8px">
                拖曳到左侧格子排课；拖回此处移除；点格内卡片可锁定 / 解锁。
              </div>
            </div>
          </div>
        </div>
      </template>
    </section>

    <section class="ios-section" style="animation-delay: 120ms">
      <div class="ios-section-title">
        <span>自动排课</span>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <n-alert
            v-if="check" :type="check.ok ? 'success' : 'warning'" :show-icon="true"
            :title="check.ok ? '前置检查通过' : `前置检查：${check.error_count} 项错误、${check.warning_count} 项提醒`"
          >
            {{ check.class_count }} 个班 · {{ check.teacher_count }} 位教师 ·
            {{ check.assignment_count }} 笔配课 · 共 {{ check.total_periods }} 节
          </n-alert>
          <n-space v-if="check && check.issues.length" vertical size="small" style="margin-top: 8px">
            <n-text v-for="(i, k) in check.issues" :key="k" depth="2" style="font-size: 13px">
              {{ i.level === 'error' ? '✕' : '⚠' }} {{ i.message }}
            </n-text>
          </n-space>
          <n-space align="end" :wrap="true" style="margin-top: 12px">
            <n-select
              v-model:value="sourceId" :options="draftOnlyOptions" placeholder="从哪份草稿开始排"
              style="width: 180px"
            />
            <n-select
              v-model:value="minutes" :options="[1, 3, 5, 10, 15, 30].map((m) => ({ label: `${m} 分钟`, value: m }))"
              style="width: 120px"
            />
            <n-select
              v-model:value="scopeGrades" :options="gradeOptions" placeholder="年级范围(空=全部)"
              style="width: 200px" multiple clearable
            />
            <n-text>允许部分解</n-text>
            <n-switch v-model:value="allowPartial" />
            <n-select
              v-if="allowPartial" v-model:value="relax" :options="relaxable.map((r) => ({ label: r.name, value: r.code }))"
              placeholder="可放宽的项目" style="width: 220px" multiple clearable
            />
            <n-button type="primary" round :loading="starting" :disabled="!sourceId" @click="onStartAuto">
              开始自动排课
            </n-button>
          </n-space>
          <n-space v-if="blockingIssues.length" vertical size="small" style="margin-top: 8px">
            <n-text v-for="(i, k) in blockingIssues" :key="k" type="error" style="font-size: 13px">
              {{ i.message }}
            </n-text>
          </n-space>
        </div>
        <div v-if="job" style="padding: 0 16px 12px; border-top: 1px solid rgba(0,0,0,0.06)">
          <div class="ios-row" style="padding: 10px 0 0">
            <div class="ios-row-main">
              <span class="ios-row-title">{{ job.source_name }} 的排课任务</span>
              <span class="ios-chip" style="margin-left: 8px">{{ jobLabel(job) }}</span>
              <span class="ios-row-sub" style="margin-left: 8px">
                已用 {{ elapsedText }} · 已出 {{ job.solutions }} 个解
                <template v-if="job.objective !== null">
                  · 目标值 {{ job.objective }}
                </template>
              </span>
            </div>
            <n-button v-if="running" size="small" text @click="onStopJob">
              提前结束
            </n-button>
            <n-button v-if="running" size="small" text type="error" @click="onCancelJob">
              取消
            </n-button>
            <n-button v-if="job.status === 'finished' && job.result_name" size="small" text type="primary" @click="openResult">
              看结果
            </n-button>
          </div>
          <n-alert v-if="job.error" type="error" style="margin-top: 8px">
            {{ job.error }}
          </n-alert>
          <template v-if="conflict">
            <div class="ios-row-sub" style="margin-top: 8px">
              {{ conflict.headline }}
              <template v-if="conflict.mode === 'joint'">
                （时间有限，这组未必是最小的组合）
              </template>
              <template v-else-if="conflict.mode">
                （时间有限，可能还有其他原因未列出）
              </template>
            </div>
            <n-space vertical size="small" style="margin-top: 4px">
              <n-text v-for="c in conflict.causes" :key="c.code" depth="2" style="font-size: 13px">
                {{ c.message }}——{{ c.suggestion }}
              </n-text>
            </n-space>
            <n-button v-if="conflict.relaxable_codes.length" size="small" round style="margin-top: 8px" @click="onRetryPartial">
              按建议放宽再排一次
            </n-button>
          </template>
          <div v-if="unscheduled.length" style="margin-top: 8px">
            <div class="ios-row-sub" style="margin-bottom: 4px">
              未排下 {{ unplacedPeriods }} 节
            </div>
            <n-space vertical size="small">
              <n-text v-for="u in unscheduled" :key="u.subject_name + u.class_names.join()" depth="2" style="font-size: 13px">
                {{ u.class_names.join('、') }}《{{ u.subject_name }}》：{{ u.periods }} 节
                {{ u.reason ? `（${u.reason}）` : '' }}
              </n-text>
            </n-space>
          </div>
        </div>
        <n-collapse style="padding: 0 16px 8px">
          <n-collapse-item title="排课任务纪录" name="jobs">
            <n-space vertical size="small">
              <n-space v-for="j in history" :key="j.job_id" align="center" :wrap="true">
                <n-text depth="2" style="font-size: 13px">
                  {{ j.source_name }} · {{ jobLabel(j) }}
                </n-text>
                <n-button size="small" text type="primary" @click="selectJob(j)">
                  查看
                </n-button>
              </n-space>
            </n-space>
          </n-collapse-item>
        </n-collapse>
      </div>
    </section>

    <section class="ios-section" style="animation-delay: 180ms">
      <div class="ios-section-title">
        <span>版本与发布</span>
        <n-button size="small" text type="primary" @click="onCreateDraft">
          新增草稿
        </n-button>
      </div>
      <div class="ios-card">
        <div class="ios-card-body">
          <div class="ios-row-sub">
            同学期可有多份草稿并存，但至多一份「已发布」。发布新版本时，旧的已发布课表会自动转为已封存。
            已发布 / 已封存的课表为快照，不可再编辑；要修改请先复制为新草稿。
          </div>
          <n-alert v-if="checkText" :type="checkOk ? 'success' : 'warning'" closable style="margin-top: 8px" @close="checkText = ''">
            {{ checkText }}
          </n-alert>
        </div>
        <n-empty v-if="!drafts.length" description="尚无课表版本" style="padding: 12px 0 24px" />
        <table v-else class="ios-table">
          <thead>
            <tr><th>名称</th><th>状态</th><th>已排格位</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in drafts" :key="t.id">
              <td>{{ t.name }}</td>
              <td>
                <span :class="t.status === 'published' ? 'ios-chip-green ios-chip' : t.status === 'draft' ? 'ios-chip-warn ios-chip' : 'ios-chip-gray ios-chip'">
                  {{ STATUS_LABELS[t.status] ?? t.status }}
                </span>
              </td>
              <td>{{ t.entry_count }}</td>
              <td>
                <n-space>
                  <n-button size="small" text @click="onCheckDraft(t)">
                    检查课表
                  </n-button>
                  <n-button v-if="t.status === 'draft'" size="small" text type="primary" @click="onPublish(t)">
                    发布
                  </n-button>
                  <n-button size="small" text @click="onDuplicateDraft(t)">
                    复制
                  </n-button>
                  <n-button size="small" text @click="openRename(t)">
                    改名
                  </n-button>
                  <n-popconfirm @positive-click="onDeleteDraft(t.id)">
                    <template #trigger>
                      <n-button size="small" text type="error">
                        删除
                      </n-button>
                    </template>
                    确定删除此课表版本？其格位将一并移除。
                  </n-popconfirm>
                </n-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="sc-result" class="ios-section" style="animation-delay: 240ms">
      <div class="ios-section-title">
        <span>结果查看（已发布课表）</span>
      </div>
      <div class="ios-card">
        <n-empty v-if="!published" description="本学期还没有已发布的课表" style="padding: 24px 0" />
        <template v-else>
          <div style="padding: 12px 16px 0">
            <n-select
              :value="resultClassId" :options="published.classes.map((c) => ({ label: c.name, value: c.id }))"
              placeholder="选择班级" style="width: 200px" filterable @update:value="(v: number) => { resultClassId = v; loadResultPeriods() }"
            />
          </div>
          <div style="padding: 12px 16px">
            <n-empty v-if="!resultClassId" description="请选择班级" />
            <TimetableGrid
              v-else :periods="resultPeriods" :entries="resultEntries" readonly
            />
          </div>
        </template>
      </div>
    </section>

    <n-modal v-model:show="formShow" preset="card" :title="editingId ? '编辑配课' : '新增配课'" style="max-width: 640px">
      <n-space vertical>
        <n-radio-group v-model:value="form.target">
          <n-radio-button value="single">
            单班
          </n-radio-button>
          <n-radio-button value="group">
            跑班群组
          </n-radio-button>
          <n-radio-button value="alternate">
            单双周组
          </n-radio-button>
        </n-radio-group>
        <n-select
          v-if="form.target === 'single'" v-model:value="form.class_id" :options="classOptions"
          placeholder="选择班级" filterable
        />
        <n-select
          v-if="form.target === 'group'" v-model:value="form.scheduling_unit_id" :options="groupOptions"
          placeholder="选择跑班群组"
        />
        <n-select
          v-if="form.target === 'alternate'" v-model:value="form.scheduling_unit_id" :options="alternateOptions"
          placeholder="选择单双周组"
        />
        <n-radio-group v-if="form.target === 'alternate'" v-model:value="form.week_parity">
          <n-radio-button value="odd">
            单周
          </n-radio-button>
          <n-radio-button value="even">
            双周
          </n-radio-button>
        </n-radio-group>
        <n-select
          v-model:value="form.subject_id" :options="subjectOptions" placeholder="选择科目" filterable
        />
        <n-space align="center">
          <n-text>只列本年级老师</n-text>
          <n-switch v-model:value="onlySameGrade" />
        </n-space>
        <n-select
          v-model:value="form.teacher_ids" :options="formTeacherOptions" placeholder="选择教师（可多选）"
          multiple filterable
        />
        <n-select
          v-model:value="form.lead_teacher_id" :options="leadOptions" placeholder="主负责教师（空=第一位）"
          clearable
        />
        <n-space align="center">
          <n-text>每周节数</n-text>
          <n-input-number v-model:value="form.periods_per_week" :min="1" style="width: 140px" />
        </n-space>
        <n-space vertical size="small">
          <n-text depth="3" style="font-size: 13px">
            连堂规则（空=不连堂）
          </n-text>
          <n-space v-for="(b, i) in form.block_rules" :key="i" align="center">
            <n-input-number v-model:value="b.block_size" :min="2" style="width: 110px" />
            <n-text>连堂</n-text>
            <n-input-number v-model:value="b.count_per_week" :min="1" style="width: 110px" />
            <n-text>次 / 周</n-text>
            <n-button size="small" text type="error" @click="removeBlock(i)">
              删除
            </n-button>
          </n-space>
          <n-button size="small" @click="addBlock">
            增加连堂规则
          </n-button>
        </n-space>
        <n-select
          v-model:value="form.required_room_type" :options="roomTypeOptions" placeholder="场地类型（可空）"
          clearable
        />
        <n-select
          v-model:value="form.room_id" :options="roomOptions" placeholder="指定场地（可空）"
          filterable clearable
        />
        <n-space align="center">
          <n-text>锁定场地</n-text>
          <n-switch v-model:value="form.lock_room" />
        </n-space>
        <n-button type="primary" round @click="saveAssignment">
          储存配课
        </n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="groupShow" preset="card" title="新建跑班群组" style="max-width: 480px">
      <n-space vertical>
        <n-input v-model:value="groupForm.name" placeholder="群组名称" />
        <n-select
          v-model:value="groupForm.class_ids" :options="classOptions" placeholder="选择至少 2 个班级"
          multiple filterable
        />
        <n-button type="primary" round @click="saveGroup">
          建立群组
        </n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="renameShow" preset="card" title="课表改名" style="max-width: 400px">
      <n-space vertical>
        <n-input v-model:value="renameValue" />
        <n-button type="primary" round @click="onRename">
          储存
        </n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="warnShow" preset="card" :title="warnTitle"
      style="max-width: 680px"
    >
      <n-space vertical>
        <template v-if="issues.length">
          <n-alert type="error" :show-icon="true">
            共 {{ issues.length }} 项冲突。通常是课表排好之后，又改了教师的不可排时段、配课的教师或节数。
            <template v-if="warnMode === 'publish'">
              仍可强制发布，但课表会照现在的样子公布。
            </template>
          </n-alert>
          <div style="max-height: 320px; overflow-y: auto">
            <div v-for="g in issueGroups" :key="g.label" style="margin-top: 8px">
              <div style="font-weight: 600">
                {{ g.label }}({{ g.items.length }})
              </div>
              <ul style="margin: 4px 0 0; padding-left: 20px">
                <li v-for="(i, k) in g.items" :key="k">
                  {{ i.message }}
                </li>
              </ul>
            </div>
          </div>
        </template>
        <n-alert v-if="incomplete" type="warning" :show-icon="true">
          共 {{ report?.remaining }} 节未排入（已排 {{ report?.placed }} / 应排 {{ report?.required }} 节）。
          <template v-if="warnMode === 'publish'">
            仍可强制发布，未排课务将不出现在课表上。
          </template>
        </n-alert>
        <table v-if="incomplete" class="ios-table">
          <thead>
            <tr><th>班级</th><th>科目</th><th>教师</th><th>未排节数</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in report?.unplaced ?? []" :key="u.course_assignment_id">
              <td>{{ u.classes.join('、') }}</td>
              <td>{{ u.subject }}</td>
              <td>{{ u.teachers.join('、') }}</td>
              <td>{{ u.remaining }} / {{ u.required }}</td>
              <td>{{ u.reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <n-space justify="end">
          <n-button @click="warnShow = false">
            {{ warnMode === 'publish' ? '取消' : '关闭' }}
          </n-button>
          <n-button
            v-if="warnMode === 'publish'" type="warning" round @click="onForcePublish"
          >
            仍要发布
          </n-button>
        </n-space>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.wb-layout { display: flex; gap: 16px; align-items: flex-start; }
.wb-tray { width: 260px; flex-shrink: 0; position: sticky; top: 8px; }
.tray-list { max-height: calc(100vh - 230px); overflow-y: auto; padding: 0 16px 12px; }
.tray-item {
  border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 10px; padding: 8px 10px;
  cursor: grab; background: rgba(52, 199, 123, 0.08); margin-bottom: 8px;
}
.tray-subject { font-weight: 600; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tray-meta { font-size: 12px; color: rgba(60, 60, 67, 0.6); }
@media (max-width: 900px) {
  .wb-layout { flex-direction: column; }
  .wb-tray { width: 100%; position: static; }
  .tray-list { max-height: none; overflow-y: visible; }
}
</style>
