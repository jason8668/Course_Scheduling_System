<script setup lang="ts">
import {
  NAlert, NButton, NEmpty, NInput, NInputNumber, NPopconfirm, NSelect,
  NSpace, NSwitch, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  CHANGE_REQUEST_STATUSES, OBJECTION_STATUSES,
  PROOFREADER_ROLE_LABELS, PROOFREADER_ROLES, PUBLISH_SCOPE_TYPES,
  approvalLevelLabel, canLockAfterProofreading, changeApprovalProgressText,
  closeObjection, createChangeRequest, createLock, createObjection, createPublishBatch,
  decideChangeRequest, decideProofreading, deleteLock, formatPublishScope, getExam,
  getPublishSettings, getPublishStatus, isObjectionClosable, isObjectionReplyable,
  isPublishBatchWithdrawable, listChangeRequests, listLocks, listObjections,
  listProofreading, listPublishBatches, nextChangeApprovalLevel, publishDue,
  replyObjection, savePublishSettings, submitProofreading, withdrawPublishBatch,
} from '@/api/exam'
import type {
  Objection, Proofreading, PublishBatch, PublishSettings, PublishStatus, ScoreChangeRequest,
  ScoreLock,
} from '@/api/exam'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'
import { classLabel } from '@/utils/labels'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
// 发布设置、锁定、发布批次只限 admin/director 写,越权时后端回 403,前端原样展示;
// 校对决定只限指定的校对人或教务,改分审批按层级限教研组长/教务,同样由后端拦截。
const canManage = computed(() => auth.hasRole('admin') || auth.hasRole('director'))

const examName = ref('')
const semesterId = ref(0)
const loading = ref(false)
const forbidden = ref(false)

const examSubjects = ref<{ subject_id: number; subject_name: string }[]>([])
const subjectOptions = computed(() =>
  examSubjects.value.map((s) => ({ label: s.subject_name, value: s.subject_id })),
)
const classes = ref<ClassUnit[]>([])
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: classLabel(c), value: c.id })),
)
function classNameFor(id: number | null | undefined): string | null {
  if (id == null) return null
  return classes.value.find((c) => c.id === id)?.name ?? null
}

// ── 发布设置 ──
const settings = ref<PublishSettings | null>(null)
const settingsForm = ref({
  proofreader_role: 'subject_leader',
  approval_levels: 1,
  objection_open: true,
})
const proofreaderRoleOptions = PROOFREADER_ROLES.map((r) => ({
  label: PROOFREADER_ROLE_LABELS[r], value: r,
}))
const approvalLevelOptions = [
  { label: '1 层', value: 1 },
  { label: '2 层', value: 2 },
]
async function reloadSettings() {
  try {
    settings.value = await getPublishSettings(examId)
    settingsForm.value = {
      proofreader_role: settings.value.proofreader_role,
      approval_levels: settings.value.approval_levels,
      objection_open: settings.value.objection_open,
    }
  } catch (e) {
    message.error((e as ApiError).detail || '发布设置加载失败')
  }
}
async function saveSettings() {
  try {
    settings.value = await savePublishSettings(examId, { ...settingsForm.value })
    message.success('发布设置已保存')
  } catch (e) {
    message.error((e as ApiError).detail || '发布设置保存失败')
  }
}

// ── 双人校对确认(KW-36) ──
const proofreadingItems = ref<Proofreading[]>([])
const proofFilter = ref({ subjectId: null as number | null, classUnitId: null as number | null })
const proofForm = ref({ subject_id: null as number | null, class_unit_id: null as number | null, note: '' })
const decideNote = ref('')
const shownProofreading = computed(() =>
  proofreadingItems.value.filter((it) =>
    (proofFilter.value.subjectId == null || it.subject_id === proofFilter.value.subjectId) &&
    (proofFilter.value.classUnitId == null || it.class_unit_id === proofFilter.value.classUnitId),
  ),
)
async function reloadProofreading() {
  try {
    proofreadingItems.value = (await listProofreading(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '校对记录加载失败')
  }
}
async function submitProof() {
  if (!proofForm.value.subject_id) { message.warning('请先选择科目'); return }
  try {
    await submitProofreading(examId, {
      subject_id: proofForm.value.subject_id,
      class_unit_id: proofForm.value.class_unit_id,
      note: proofForm.value.note.trim() || null,
    })
    message.success('已提交校对,等待校对人确认')
    proofForm.value.note = ''
    await reloadProofreading()
  } catch (e) {
    message.error((e as ApiError).detail || '提交校对失败')
  }
}
async function decideProof(id: number, decision: string) {
  try {
    await decideProofreading(examId, id, {
      decision,
      note: decideNote.value.trim() || null,
    })
    message.success(`校对已${decision}`)
    decideNote.value = ''
    await reloadProofreading()
  } catch (e) {
    message.error((e as ApiError).detail || '校对决定失败')
  }
}

// ── 提交与锁定(KW-37) ──
const locks = ref<ScoreLock[]>([])
const lockForm = ref({ subject_id: null as number | null, class_unit_id: null as number | null })
/** 锁定前置:该范围校对须已通过,否则后端 409;按钮据此置灰,先提示后拦截。 */
const lockReady = computed(() =>
  lockForm.value.subject_id != null &&
  canLockAfterProofreading(proofreadingItems.value, lockForm.value.subject_id, lockForm.value.class_unit_id),
)
async function reloadLocks() {
  try {
    locks.value = (await listLocks(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '锁定清单加载失败')
  }
}
async function createScoreLock() {
  if (!lockForm.value.subject_id) { message.warning('请先选择科目'); return }
  if (!lockReady.value) { message.warning('该范围校对尚未通过,不能锁定'); return }
  try {
    await createLock(examId, {
      subject_id: lockForm.value.subject_id,
      class_unit_id: lockForm.value.class_unit_id,
    })
    message.success('成绩已锁定,锁定后改分须走审批')
    await reloadLocks()
  } catch (e) {
    message.error((e as ApiError).detail || '锁定失败')
  }
}
async function removeLock(l: ScoreLock) {
  try {
    await deleteLock(examId, l.id)
    message.success('已解锁')
    await reloadLocks()
  } catch (e) {
    message.error((e as ApiError).detail || '解锁失败')
  }
}

// ── 改分审批与留痕(KW-38) ──
const changeRequests = ref<ScoreChangeRequest[]>([])
const changeFilterStatus = ref<string | null>(null)
const changeForm = ref({ score_id: null as number | null, new_score: null as number | null, reason: '' })
const changeDecideNote = ref('')
const changeStatusOptions = CHANGE_REQUEST_STATUSES.map((s) => ({ label: s, value: s }))
const shownChangeRequests = computed(() =>
  changeFilterStatus.value
    ? changeRequests.value.filter((r) => r.status === changeFilterStatus.value)
    : changeRequests.value,
)
async function reloadChangeRequests() {
  try {
    changeRequests.value = (await listChangeRequests(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '改分申请加载失败')
  }
}
async function submitChangeRequest() {
  if (!changeForm.value.score_id) { message.warning('请填写成绩编号'); return }
  if (!changeForm.value.reason.trim()) { message.warning('请填写改分原因'); return }
  try {
    await createChangeRequest(examId, {
      score_id: changeForm.value.score_id,
      new_score: changeForm.value.new_score,
      reason: changeForm.value.reason.trim(),
    })
    message.success('改分申请已提交,等待审批')
    changeForm.value = { score_id: null, new_score: null, reason: '' }
    await reloadChangeRequests()
  } catch (e) {
    message.error((e as ApiError).detail || '改分申请提交失败')
  }
}
async function decideChange(id: number, decision: string) {
  try {
    await decideChangeRequest(examId, id, {
      decision,
      note: changeDecideNote.value.trim() || null,
    })
    message.success(`改分申请已${decision}`)
    changeDecideNote.value = ''
    await reloadChangeRequests()
  } catch (e) {
    message.error((e as ApiError).detail || '改分审批失败')
  }
}
function approvalLevels(): number {
  return settings.value?.approval_levels ?? 1
}

// ── 成绩分批发布(KW-39) ──
const batches = ref<PublishBatch[]>([])
const publishStatus = ref<PublishStatus | null>(null)
const batchForm = ref({
  scope_type: '年级',
  scope_value: null as number | null,
  publish_at: '',
  note: '',
})
const scopeTypeOptions = PUBLISH_SCOPE_TYPES.map((t) => ({ label: t, value: t }))
async function reloadBatches() {
  try {
    batches.value = (await listPublishBatches(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '发布批次加载失败')
  }
}
async function reloadPublishStatus() {
  try {
    publishStatus.value = await getPublishStatus(examId)
  } catch (e) {
    message.error((e as ApiError).detail || '发布状态加载失败')
  }
}
async function createBatch() {
  if (batchForm.value.scope_value == null) { message.warning('请填写发布范围'); return }
  try {
    await createPublishBatch(examId, {
      scope_type: batchForm.value.scope_type,
      scope_value: batchForm.value.scope_value,
      publish_at: batchForm.value.publish_at || null,
      note: batchForm.value.note.trim() || null,
    })
    message.success(batchForm.value.publish_at ? '已建定时发布批次' : '成绩已发布')
    batchForm.value = { scope_type: '年级', scope_value: null, publish_at: '', note: '' }
    await Promise.all([reloadBatches(), reloadPublishStatus()])
  } catch (e) {
    message.error((e as ApiError).detail || '发布失败')
  }
}
async function withdrawBatch(b: PublishBatch) {
  try {
    await withdrawPublishBatch(examId, b.id)
    message.success('发布已撤回,撤回留痕')
    await Promise.all([reloadBatches(), reloadPublishStatus()])
  } catch (e) {
    message.error((e as ApiError).detail || '撤回失败')
  }
}
async function runPublishDue() {
  try {
    const res = await publishDue(examId)
    message.success(`到期发布完成,本次发布 ${res.published} 个批次`)
    await Promise.all([reloadBatches(), reloadPublishStatus()])
  } catch (e) {
    message.error((e as ApiError).detail || '到期发布失败')
  }
}

// ── 查分与成绩异议登记(KW-40) ──
const objections = ref<Objection[]>([])
const objectionFilterStatus = ref<string | null>(null)
const objectionForm = ref({ score_id: null as number | null, content: '' })
const replyDrafts = ref<Record<number, string>>({})
const objectionStatusOptions = OBJECTION_STATUSES.map((s) => ({ label: s, value: s }))
const shownObjections = computed(() =>
  objectionFilterStatus.value
    ? objections.value.filter((o) => o.status === objectionFilterStatus.value)
    : objections.value,
)
async function reloadObjections() {
  try {
    objections.value = (await listObjections(examId)).items
  } catch (e) {
    message.error((e as ApiError).detail || '异议列表加载失败')
  }
}
async function submitObjection() {
  if (!objectionForm.value.score_id) { message.warning('请填写成绩编号'); return }
  if (!objectionForm.value.content.trim()) { message.warning('请填写异议内容'); return }
  try {
    await createObjection(examId, {
      score_id: objectionForm.value.score_id,
      content: objectionForm.value.content.trim(),
    })
    message.success('异议已登记,等待任课教师复核')
    objectionForm.value = { score_id: null, content: '' }
    await reloadObjections()
  } catch (e) {
    message.error((e as ApiError).detail || '异议登记失败')
  }
}
async function replyToObjection(o: Objection) {
  const reply = (replyDrafts.value[o.id] ?? '').trim()
  if (!reply) { message.warning('请填写回复内容'); return }
  try {
    await replyObjection(examId, o.id, { reply })
    message.success('已回复异议')
    delete replyDrafts.value[o.id]
    await reloadObjections()
  } catch (e) {
    message.error((e as ApiError).detail || '回复失败')
  }
}
async function closeObjectionRow(o: Objection) {
  try {
    await closeObjection(examId, o.id)
    message.success('异议已关闭')
    await reloadObjections()
  } catch (e) {
    message.error((e as ApiError).detail || '关闭失败')
  }
}

async function reloadAll() {
  loading.value = true
  forbidden.value = false
  try {
    const exam = await getExam(examId)
    examName.value = exam.name
    semesterId.value = exam.semester_id
    examSubjects.value = (exam.subjects ?? []).map((s) => ({
      subject_id: s.subject_id, subject_name: s.subject_name,
    }))
    classes.value = await listClassUnits(exam.semester_id)
    if (examSubjects.value.length) {
      proofForm.value.subject_id = examSubjects.value[0].subject_id
      lockForm.value.subject_id = examSubjects.value[0].subject_id
    }
    await Promise.all([
      reloadSettings(), reloadProofreading(), reloadLocks(), reloadChangeRequests(),
      reloadBatches(), reloadPublishStatus(), reloadObjections(),
    ])
  } catch (e) {
    if ((e as ApiError).status === 403) forbidden.value = true
    else message.error((e as ApiError).detail || '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => { void reloadAll() })

function goBack() {
  void router.push({ name: 'exam-exam-detail', params: { id: examId } })
}
</script>

<template>
  <div class="ios-page">
    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <n-button text type="primary" @click="goBack">← 考试详情</n-button>
      <h1 class="ios-title">{{ examName ? `${examName} · 发布与校对锁定` : '发布与校对锁定' }}</h1>
    </div>
    <n-alert v-if="forbidden" type="error" style="margin-top: 16px">
      无权查看该考试(不在你的可见范围内)。
    </n-alert>
    <n-empty v-else-if="!loading && !examName" description="找不到该考试" style="margin-top: 24px" />

    <template v-else-if="examName">
      <!-- 发布设置 -->
      <div class="ios-section">
        <div class="ios-section-title">发布设置</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            校对人、审批层级、发布顺序、异议入口四项口径仍待学校确认,确认前请按当前默认值使用。
          </n-text>
          <n-space :wrap="true" align="center">
            <span style="font-size: 13px">校对人</span>
            <n-select
              v-model:value="settingsForm.proofreader_role" :options="proofreaderRoleOptions"
              style="width: 130px" data-testid="publish-proofreader-role"
            />
            <span style="font-size: 13px">改分审批层级</span>
            <n-select
              v-model:value="settingsForm.approval_levels" :options="approvalLevelOptions"
              style="width: 90px" data-testid="publish-approval-levels"
            />
            <span style="font-size: 13px">异议入口</span>
            <n-switch v-model:value="settingsForm.objection_open" data-testid="publish-objection-open">
              <template #checked>开放</template>
              <template #unchecked>关闭</template>
            </n-switch>
            <n-button
              v-if="canManage" type="primary" data-testid="publish-settings-save"
              @click="saveSettings"
            >保存设置</n-button>
          </n-space>
        </div></div>
      </div>

      <!-- 双人校对确认(KW-36) -->
      <div class="ios-section">
        <div class="ios-section-title">双人校对确认</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            成绩提交前须经第二人校对确认(录入人+校对人),校对通过才能进入锁定,校对记录留痕。
            提交校对前该范围成绩须已全部提交,否则后端拒绝;校对人由发布设置里的校对人角色决定,不能是录入人本人。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="proofForm.subject_id" :options="subjectOptions" clearable
              placeholder="选择科目" style="width: 140px"
            />
            <n-select
              v-model:value="proofForm.class_unit_id" :options="classOptions" clearable
              placeholder="全部班级(全科)" style="width: 170px"
            />
            <n-input v-model:value="proofForm.note" placeholder="备注(选填)" style="width: 180px" />
            <n-button type="primary" data-testid="proofreading-submit" @click="submitProof">提交校对</n-button>
          </n-space>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <n-select
              v-model:value="proofFilter.subjectId" :options="subjectOptions" clearable
              placeholder="按科目筛选" style="width: 140px"
            />
            <n-select
              v-model:value="proofFilter.classUnitId" :options="classOptions" clearable
              placeholder="按班级筛选" style="width: 170px"
            />
            <n-input v-model:value="decideNote" placeholder="校对决定备注(选填)" style="width: 180px" />
          </n-space>
          <n-empty v-if="shownProofreading.length === 0" description="暂无校对记录" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>科目</th><th>年级</th><th>班级</th><th>提交人</th><th>校对人</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="it in shownProofreading" :key="it.id">
                <td>{{ it.subject_name }}</td>
                <td>{{ it.grade != null ? `${it.grade}年级` : (it.class_name ? '—' : '全科') }}</td>
                <td>{{ it.class_name ?? '全科' }}</td>
                <td>{{ it.submitted_by_name || '—' }}</td>
                <td>{{ it.proofreader_name || '—' }}</td>
                <td>{{ it.status }}</td>
                <td>{{ it.note ?? '—' }}</td>
                <td>
                  <n-space v-if="it.status === '待校对'" :wrap="true">
                    <n-button
                      size="small" type="primary"
                      :data-testid="`proofreading-pass-${it.id}`"
                      @click="decideProof(it.id, '通过')"
                    >通过</n-button>
                    <n-popconfirm @positive-click="decideProof(it.id, '退回')">
                      <template #trigger>
                        <n-button size="small" type="error" :data-testid="`proofreading-reject-${it.id}`">退回</n-button>
                      </template>
                      确定退回这条校对?退回后须重新提交校对。
                    </n-popconfirm>
                  </n-space>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>

      <!-- 提交与锁定(KW-37) -->
      <div class="ios-section">
        <div class="ios-section-title">提交与锁定</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            教师提交后成绩锁定,锁定后本人不能直接修改,只能走改分审批;锁定状态在进度看板可见。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="lockForm.subject_id" :options="subjectOptions" clearable
              placeholder="选择科目" style="width: 140px"
            />
            <n-select
              v-model:value="lockForm.class_unit_id" :options="classOptions" clearable
              placeholder="全部班级(全科)" style="width: 170px"
            />
            <n-button
              v-if="canManage" type="primary" :disabled="!lockReady"
              data-testid="lock-create" @click="createScoreLock"
            >锁定成绩</n-button>
            <n-text
              v-if="lockForm.subject_id && !lockReady" type="warning" style="font-size: 12px"
              data-testid="lock-not-ready"
            >该范围校对尚未通过,不能锁定</n-text>
          </n-space>
          <n-empty v-if="locks.length === 0" description="暂无锁定记录" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>科目</th><th>年级</th><th>班级</th><th>锁定人</th><th>锁定时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="l in locks" :key="l.id">
                <td>{{ l.subject_name }}</td>
                <td>{{ l.grade != null ? `${l.grade}年级` : (l.class_name ? '—' : '全科') }}</td>
                <td>{{ l.class_name ?? '全科' }}</td>
                <td>{{ l.locked_by_name || '—' }}</td>
                <td>{{ l.locked_at ? l.locked_at.slice(0, 19).replace('T', ' ') : '—' }}</td>
                <td>
                  <n-popconfirm v-if="canManage" @positive-click="removeLock(l)">
                    <template #trigger>
                      <n-button size="small" text type="error" :data-testid="`lock-delete-${l.id}`">解锁</n-button>
                    </template>
                    确定解锁「{{ l.subject_name }}{{ l.class_name ? ` · ${l.grade != null ? `${l.grade}年级` : ''}${l.class_name}` : ' · 全科' }}」?解锁后可直接修改成绩。
                  </n-popconfirm>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>

      <!-- 改分审批与留痕(KW-38) -->
      <div class="ios-section">
        <div class="ios-section-title">改分审批</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            锁定后改分须提交申请(原分数、新分数、原因),审批通过后生效,前后值和审批人全程留痕可查。
            未锁定的成绩直接修改即可,无需改分审批;同一成绩同时只能有一条待审批申请。
            {{ approvalLevels() === 2 ? '当前两层审批:第一层教研组长、第二层教务,任一层驳回即终结。' : '当前一层审批:教研组长或教务一人决定。' }}
          </n-text>
          <n-space :wrap="true" align="center">
            <n-input-number
              v-model:value="changeForm.score_id" placeholder="成绩编号" :min="1"
              style="width: 130px" data-testid="change-score-id"
            />
            <n-input-number
              v-model:value="changeForm.new_score" placeholder="新分数(空为取消)" :min="0"
              style="width: 150px" data-testid="change-new-score"
            />
            <n-input v-model:value="changeForm.reason" placeholder="改分原因(必填)" style="width: 200px" />
            <n-button type="primary" data-testid="change-request-create" @click="submitChangeRequest">提交改分申请</n-button>
          </n-space>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <n-select
              v-model:value="changeFilterStatus" :options="changeStatusOptions" clearable
              placeholder="按状态筛选" style="width: 130px"
            />
            <n-input v-model:value="changeDecideNote" placeholder="审批备注(选填)" style="width: 180px" />
          </n-space>
          <n-empty v-if="shownChangeRequests.length === 0" description="暂无改分申请" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>学生</th><th>科目</th><th>原分数</th><th>新分数</th><th>原因</th><th>申请人</th><th>状态与进度</th><th>审批记录</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="r in shownChangeRequests" :key="r.id">
                <td>{{ r.student_name || '—' }}</td>
                <td>{{ r.subject_name }}</td>
                <td>{{ r.old_score ?? '—' }}</td>
                <td>{{ r.new_score ?? '—' }}</td>
                <td>{{ r.reason }}</td>
                <td>{{ r.requested_by_name || '—' }}</td>
                <td>
                  {{ r.status }}<br>
                  <n-text depth="3" style="font-size: 12px">{{ changeApprovalProgressText(r, approvalLevels()) }}</n-text>
                </td>
                <td>
                  <div
                    v-for="a in r.approvals" :key="`${a.level}-${a.approver_name}`"
                    style="font-size: 12px"
                  >第 {{ a.level }} 层({{ approvalLevelLabel(a.level, approvalLevels()) }}):{{ a.approver_name }} {{ a.decision }}{{ a.note ? ` · ${a.note}` : '' }}</div>
                  <span v-if="r.approvals.length === 0">—</span>
                </td>
                <td>
                  <n-space v-if="r.status === '待审批'" :wrap="true">
                    <n-button
                      size="small" type="primary"
                      :data-testid="`change-approve-${r.id}`"
                      @click="decideChange(r.id, '通过')"
                    >通过{{ nextChangeApprovalLevel(r, approvalLevels()) != null ? `(第 ${nextChangeApprovalLevel(r, approvalLevels())} 层)` : '' }}</n-button>
                    <n-popconfirm @positive-click="decideChange(r.id, '驳回')">
                      <template #trigger>
                        <n-button size="small" type="error" :data-testid="`change-reject-${r.id}`">驳回</n-button>
                      </template>
                      确定驳回这条改分申请?驳回后申请终结。
                    </n-popconfirm>
                  </n-space>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>

      <!-- 成绩分批发布(KW-39) -->
      <div class="ios-section">
        <div class="ios-section-title">成绩分批发布</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            教务可按年级、按班级分批发布成绩,也可定时发布;发布后可撤回(撤回留痕)。
            不填发布时间即当场发布;填了未来时间则为待发布,到期后由定时任务或“执行到期发布”发布。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-select
              v-model:value="batchForm.scope_type" :options="scopeTypeOptions"
              style="width: 100px"
            />
            <n-input-number
              v-if="batchForm.scope_type === '年级'" v-model:value="batchForm.scope_value"
              placeholder="年级,如 7" :min="1" style="width: 120px"
            />
            <n-select
              v-else v-model:value="batchForm.scope_value" :options="classOptions" clearable
              placeholder="选择班级" style="width: 170px"
            />
            <input
              v-model="batchForm.publish_at" type="datetime-local" style="width: 190px"
              data-testid="publish-batch-at"
            >
            <n-input v-model:value="batchForm.note" placeholder="备注(选填)" style="width: 160px" />
            <n-button
              v-if="canManage" type="primary" data-testid="publish-batch-create"
              @click="createBatch"
            >{{ batchForm.publish_at ? '新建定时发布' : '发布成绩' }}</n-button>
            <n-button
              v-if="canManage" data-testid="publish-due" @click="runPublishDue"
            >执行到期发布</n-button>
          </n-space>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <span style="font-size: 13px">发布状态总览:</span>
            <span
              :class="publishStatus?.all_published ? 'ios-chip' : 'ios-chip-gray'"
              data-testid="publish-all-published"
            >{{ publishStatus?.all_published ? '全部已发布' : '未全部发布' }}</span>
            <span
              v-for="b in publishStatus?.batches ?? []" :key="`${b.scope_type}-${b.scope_value}`"
              style="font-size: 12px"
            >{{ formatPublishScope(b.scope_type, b.scope_value, classNameFor(b.scope_type === '班级' ? b.scope_value : null)) }}:{{ b.status }}{{ b.publish_at ? `(${b.publish_at.slice(0, 16).replace('T', ' ')})` : '' }}</span>
          </n-space>
          <n-empty v-if="batches.length === 0" description="暂无发布批次" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>发布范围</th><th>状态</th><th>发布时间</th><th>发布人</th><th>备注</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="b in batches" :key="b.id">
                <td>{{ formatPublishScope(b.scope_type, b.scope_value, classNameFor(b.scope_type === '班级' ? b.scope_value : null)) }}</td>
                <td>{{ b.status }}</td>
                <td>{{ b.publish_at ? b.publish_at.slice(0, 16).replace('T', ' ') : '当场发布' }}</td>
                <td>{{ b.published_by_name || '—' }}</td>
                <td>{{ b.note ?? '—' }}</td>
                <td>
                  <n-popconfirm v-if="canManage && isPublishBatchWithdrawable(b)" @positive-click="withdrawBatch(b)">
                    <template #trigger>
                      <n-button size="small" text type="error" :data-testid="`publish-batch-withdraw-${b.id}`">撤回</n-button>
                    </template>
                    确定撤回「{{ formatPublishScope(b.scope_type, b.scope_value, classNameFor(b.scope_type === '班级' ? b.scope_value : null)) }}」的成绩发布?撤回留痕。
                  </n-popconfirm>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>

      <!-- 查分与成绩异议登记(KW-40) -->
      <div class="ios-section">
        <div class="ios-section-title">查分与成绩异议登记</div>
        <div class="ios-card"><div class="ios-card-body">
          <n-alert
            v-if="settings && !settings.objection_open" type="warning" style="margin-bottom: 8px"
            data-testid="objection-closed"
          >
            本考试未开放成绩异议入口(发布设置里可开启),登记将被后端拒绝。
          </n-alert>
          <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
            学生对成绩有疑问,可由教师/教务代为登记异议,由任课教师复核后回复处理结果,形成闭环记录。
            异议须先回复才能关闭;只有待复核的异议能回复,只有已回复的异议能关闭。
          </n-text>
          <n-space :wrap="true" align="center">
            <n-input-number
              v-model:value="objectionForm.score_id" placeholder="成绩编号" :min="1"
              style="width: 130px" data-testid="objection-score-id"
            />
            <n-input v-model:value="objectionForm.content" placeholder="异议内容(必填)" style="width: 260px" />
            <n-button
              type="primary" :disabled="settings != null && !settings.objection_open"
              data-testid="objection-create" @click="submitObjection"
            >登记异议</n-button>
          </n-space>
          <n-space :wrap="true" align="center" style="margin-top: 12px">
            <n-select
              v-model:value="objectionFilterStatus" :options="objectionStatusOptions" clearable
              placeholder="按状态筛选" style="width: 130px"
            />
          </n-space>
          <n-empty v-if="shownObjections.length === 0" description="暂无异议记录" style="margin-top: 12px" />
          <table v-else class="ios-table" style="margin-top: 12px">
            <thead><tr><th>学生</th><th>科目</th><th>异议内容</th><th>登记角色</th><th>状态</th><th>回复</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="o in shownObjections" :key="o.id">
                <td>{{ o.student_name || '—' }}</td>
                <td>{{ o.subject_name }}</td>
                <td>{{ o.content }}</td>
                <td>{{ o.raised_by_role || '—' }}</td>
                <td>{{ o.status }}</td>
                <td>{{ o.reply ? `${o.reply}${o.replied_by_name ? `(${o.replied_by_name})` : ''}` : '—' }}</td>
                <td>
                  <n-space :wrap="true">
                    <template v-if="isObjectionReplyable(o)">
                      <n-input
                        v-model:value="replyDrafts[o.id]" placeholder="回复内容"
                        style="width: 160px" :data-testid="`objection-reply-input-${o.id}`"
                      />
                      <n-button
                        size="small" type="primary"
                        :data-testid="`objection-reply-${o.id}`"
                        @click="replyToObjection(o)"
                      >回复</n-button>
                    </template>
                    <n-popconfirm v-if="isObjectionClosable(o)" @positive-click="closeObjectionRow(o)">
                      <template #trigger>
                        <n-button size="small" :data-testid="`objection-close-${o.id}`">关闭</n-button>
                      </template>
                      确定关闭这条异议?关闭后形成闭环记录。
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>
        </div></div>
      </div>
    </template>
  </div>
</template>
