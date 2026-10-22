<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NInput, NInputNumber, NPopconfirm, NSpace, NTag, NText,
  NUpload,
  useDialog, useMessage,
} from 'naive-ui'
import type { UploadCustomRequestOptions } from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  createBackup, deleteBackup, downloadBackup, listBackups, restoreBackup, restoreUpload,
} from '@/api/backups'
import type { Backup, RestoreResult } from '@/api/backups'
import {
  demoDataStatus, getDingTalkSettings, getSchedulingSettings, getSchoolSettings, loadDemoData,
  saveDingTalkSettings, testDingTalk,
  saveSchedulingSettings, saveSchoolSettings,
} from '@/api/assignments'
import { getSmtp, saveSmtp } from '@/api/notifications'
import { getPatrolSettings, savePatrolSettings } from '@/api/substitutionLog'
import {
  RELEASES_URL, UPGRADE_GUIDE_URL, dismissUpgradeNotice, getUpdateStatus, getUpgradeNotice,
} from '@/api/system'
import type { UpdateStatus, UpgradeNotice } from '@/api/system'
import { resetWizard } from '@/api/wizard'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const wizard = useWizardStore()
const auth = useAuthStore()

const isAdmin = () => auth.hasRole('admin')

// ── 系统版本与新版本提醒 ──
const update = ref<UpdateStatus | null>(null)
const checkingUpdate = ref(false)

function twTime(iso: string): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-TW', { hour12: false })
}

async function loadUpdate(refresh = false) {
  checkingUpdate.value = true
  try {
    update.value = await getUpdateStatus(refresh)
    if (refresh && update.value.error) message.warning(update.value.error)
    else if (refresh) {
      message.success(update.value.update_available
        ? `有新版本 ${update.value.latest}` : '目前已是最新版本')
    }
  } catch (e) {
    message.error((e as ApiError).message || '无法取得版本信息')
  } finally {
    checkingUpdate.value = false
  }
}

// ── 结构升级后的一次性提示(v1.3.0):升级前自动备份了哪一份 ──
const upgradeNotice = ref<UpgradeNotice | null>(null)
async function loadUpgradeNotice() {
  try {
    upgradeNotice.value = await getUpgradeNotice()
  } catch {
    upgradeNotice.value = null // 旧资料或权限问题:不显示即可,不影响其他功能
  }
}
async function onDismissUpgradeNotice() {
  await dismissUpgradeNotice()
  upgradeNotice.value = null
}

// ── 备份与还原 ──
const backups = ref<Backup[]>([])
const busy = ref(false)

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function reloadBackups() {
  if (!isAdmin()) return
  backups.value = await listBackups()
}

async function onCreateBackup() {
  busy.value = true
  try {
    await createBackup()
    message.success('已建立备份')
    await reloadBackups()
  } catch (e) {
    message.error((e as ApiError).message || '备份失败')
  } finally {
    busy.value = false
  }
}

async function onDeleteBackup(name: string) {
  await deleteBackup(name)
  message.success('已删除备份')
  await reloadBackups()
}

async function redirectToLogin() {
  await auth.logout().catch(() => {})
  router.push({ name: 'login' })
}

async function afterRestore(r: RestoreResult) {
  // 还原后所有 session 已失效,需重新登录。若有可忽略的警告,先以对话框让管理员看见
  // (讯息在导向登录页后会消失,警告不能只用一闪即逝的 toast)。
  if (r.warnings.length > 0) {
    dialog.warning({
      title: '还原完成,但有可忽略的警告',
      content: () => h('div', [
        h('p', `现状已备份为 ${r.presafe_backup}。以下警告不影响资料,通常为跨版本的设置参数:`),
        ...r.warnings.map((w) => h('p', { style: 'font-size:12px;color:#999;margin:4px 0' }, w)),
      ]),
      positiveText: '知道了,重新登录',
      maskClosable: false,
      onPositiveClick: redirectToLogin,
      onClose: redirectToLogin,
    })
    return
  }
  message.success(`还原完成(现状已备份为 ${r.presafe_backup}),请重新登录`)
  await redirectToLogin()
}

async function onRestore(name: string) {
  busy.value = true
  try {
    const r = await restoreBackup(name)
    await afterRestore(r)
  } catch (e) {
    message.error((e as ApiError).message || '还原失败')
  } finally {
    busy.value = false
  }
}

async function onUploadRestore({ file, onFinish, onError }: UploadCustomRequestOptions) {
  busy.value = true
  try {
    const r = await restoreUpload(file.file as File)
    onFinish()
    await afterRestore(r)
  } catch (e) {
    onError()
    message.error((e as Error).message || '上传还原失败')
  } finally {
    busy.value = false
  }
}

const smtp = ref({
  host: '', port: 25, user: '', password: '', sender: '', use_tls: false,
})
const configured = ref(false)
const hasPassword = ref(false)
const savingSmtp = ref(false)

const maxOvertime = ref(8)
const savingScheduling = ref(false)

const schoolName = ref('')

// ── 巡堂表的记录说明(各校的代码不同)──
const patrolLegend = ref('')
const savingPatrol = ref(false)
async function onSavePatrol() {
  savingPatrol.value = true
  try {
    // 留空送出 = 恢复默认;后端会回传实际生效的文字
    patrolLegend.value = (await savePatrolSettings({ legend: patrolLegend.value })).legend
    message.success('已储存巡堂表设置')
  } catch (e) {
    message.error((e as ApiError).message || '储存失败')
  } finally {
    savingPatrol.value = false
  }
}
// ── 钉钉群机器人 ──
const dingtalk = ref({ webhook: '', secret: '' })
const dingtalkHasSecret = ref(false)
const savingDingtalk = ref(false)
const testingDingtalk = ref(false)

async function onSaveDingtalk() {
  savingDingtalk.value = true
  try {
    const r = await saveDingTalkSettings(dingtalk.value.webhook, dingtalk.value.secret)
    dingtalk.value.webhook = r.webhook
    dingtalk.value.secret = ''
    dingtalkHasSecret.value = r.has_secret
    message.success(r.configured ? '已保存钉钉设置' : '已清空钉钉 Webhook,群通知停用')
  } catch (e) {
    message.error((e as ApiError).message || '保存失败')
  } finally {
    savingDingtalk.value = false
  }
}

async function onTestDingtalk() {
  testingDingtalk.value = true
  try {
    await testDingTalk(dingtalk.value.webhook, dingtalk.value.secret)
    message.success('测试消息已发送,请到钉钉群确认')
  } catch (e) {
    message.error((e as ApiError).message || '发送失败')
  } finally {
    testingDingtalk.value = false
  }
}

const savingSchool = ref(false)

async function onSaveSchool() {
  if (!schoolName.value.trim()) { message.warning('请输入校名'); return }
  savingSchool.value = true
  try {
    schoolName.value = (await saveSchoolSettings({ school_name: schoolName.value })).school_name
    message.success('已更新校名')
  } catch (e) {
    message.error((e as ApiError).message || '储存失败')
  } finally {
    savingSchool.value = false
  }
}

onMounted(async () => {
  if (!isAdmin()) return
  // 查新版本可能要连外等几秒,不挡住其他设置载入
  void loadUpdate()
  void loadUpgradeNotice()
  const s = await getSmtp()
  smtp.value = { host: s.host, port: s.port, user: s.user, password: '', sender: s.sender, use_tls: s.use_tls }
  configured.value = s.configured
  hasPassword.value = s.has_password
  maxOvertime.value = (await getSchedulingSettings()).max_overtime
  schoolName.value = (await getSchoolSettings()).school_name
  const dt = await getDingTalkSettings()
  dingtalk.value.webhook = dt.webhook
  dingtalkHasSecret.value = dt.has_secret
  patrolLegend.value = (await getPatrolSettings()).legend
  const demo = await demoDataStatus()
  demoAvailable.value = demo.available
  demoReason.value = demo.reason
  demoSchool.value = demo.school_name
  await reloadBackups()
})

// ── 示范资料 ──
const demoAvailable = ref(false)
const demoReason = ref('')
const demoSchool = ref('')
const loadingDemo = ref(false)

async function onLoadDemo() {
  loadingDemo.value = true
  try {
    const r = await loadDemoData()
    schoolName.value = r.school_name
    demoAvailable.value = false
    demoReason.value = '示范资料已载入。'
    message.success(
      `已建立 ${r.classes} 班、${r.teachers} 位教师、${r.assignments} 笔配课`
      + `(共 ${r.total_periods} 节)。可以到「自动排课」试跑了。`,
      { duration: 8000 },
    )
  } catch (e) {
    message.error((e as ApiError).message || '载入失败')
  } finally {
    loadingDemo.value = false
  }
}

async function onSaveScheduling() {
  savingScheduling.value = true
  try {
    const s = await saveSchedulingSettings({ max_overtime: maxOvertime.value })
    maxOvertime.value = s.max_overtime
    message.success('已储存排课设置')
  } catch (e) {
    message.error((e as ApiError).message || '储存失败')
  } finally {
    savingScheduling.value = false
  }
}

async function onSaveSmtp() {
  savingSmtp.value = true
  try {
    const s = await saveSmtp(smtp.value)
    configured.value = s.configured
    hasPassword.value = s.has_password
    smtp.value.password = ''
    message.success('已储存 SMTP 设置')
  } catch (e) {
    message.error((e as ApiError).message || '储存失败')
  } finally {
    savingSmtp.value = false
  }
}

async function onResetWizard() {
  await resetWizard()
  await wizard.fetch()
  message.success('已重新启动设置精灵')
  router.push({ name: 'wizard' })
}
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">系统管理</h1>

    <n-card v-if="isAdmin()" title="系统版本" data-testid="version-card">
      <n-space vertical>
        <n-alert
          v-if="upgradeNotice" :type="upgradeNotice.error ? 'error' : 'success'"
          :title="`系统已升级到 ${upgradeNotice.version}(${upgradeNotice.at})`"
          data-testid="upgrade-notice"
        >
          <template v-if="!upgradeNotice.error">
            升级时资料库结构有变更,系统在升级前已<b>自动备份</b>:<code>{{ upgradeNotice.backup }}</code>。
            这份备份在下方「资料备份与还原」的清单里(标示「升级前自动备份」),不会被每日备份轮替删除。
            若要退回旧版,请先用这份备份还原,再照升级指南把版本号改回旧版。
          </template>
          <template v-else>
            升级前的<b>自动备份没有成功</b>({{ upgradeNotice.error }}),系统已照常升级、可以正常使用。
            建议现在就按下方「立即备份」留一份。若要退回旧版,可用升级前一晚的每日自动备份还原,
            或照升级指南的「退回指令」操作。
          </template>
          <div style="margin-top: 6px">
            <a :href="UPGRADE_GUIDE_URL" target="_blank" rel="noopener">升级指南</a>
            ・
            <n-button text type="primary" data-testid="upgrade-notice-dismiss" @click="onDismissUpgradeNotice">
              知道了
            </n-button>
          </div>
        </n-alert>
        <n-space align="center">
          <n-text style="width: 72px">目前版本</n-text>
          <n-tag :type="update?.update_available ? 'warning' : 'success'" data-testid="version-current">
            {{ update?.current ?? '读取中…' }}
          </n-tag>
          <template v-if="update?.enabled && update.latest">
            <n-text depth="3" style="margin-left: 12px">最新正式版</n-text>
            <n-tag data-testid="version-latest">{{ update.latest }}</n-tag>
          </template>
        </n-space>

        <n-alert
          v-if="update?.update_available" type="warning" :bordered="false"
          data-testid="version-update"
        >
          有新版本 <b>{{ update.latest }}</b> 可以升级。升级前请先「立即备份」,
          再照升级指南把 <code>.env</code> 的 <code>IMAGE_TAG</code> 改成 {{ update.latest }},
          执行 <code>docker compose pull</code> 与 <code>docker compose up -d</code>。
          系统不会自动升级。
          <div style="margin-top: 6px">
            <a :href="update.latest_url || RELEASES_URL" target="_blank" rel="noopener">这一版更新了什么</a>
            ・
            <a :href="UPGRADE_GUIDE_URL" target="_blank" rel="noopener">升级指南</a>
          </div>
        </n-alert>
        <n-alert
          v-else-if="update?.enabled && update.latest && update.current !== 'dev'
            && !update.current.startsWith('main')"
          type="success" :bordered="false" data-testid="version-uptodate"
        >
          目前已是最新版本。
        </n-alert>
        <n-alert
          v-if="update?.enabled && update.error" type="info" :bordered="false"
          data-testid="version-error"
        >
          {{ update.error }}。不影响系统任何功能;可到
          <a :href="RELEASES_URL" target="_blank" rel="noopener">GitHub Releases</a> 自行查看最新版本。
        </n-alert>
        <n-text v-if="update && !update.enabled" depth="3" data-testid="version-disabled">
          新版本检查已关闭(<code>.env</code> 设置 <code>UPDATE_CHECK_ENABLED=false</code>)。
        </n-text>

        <n-space v-if="update?.enabled" align="center">
          <n-button
            size="small" :loading="checkingUpdate" data-testid="version-check"
            @click="loadUpdate(true)"
          >
            立即检查
          </n-button>
          <n-text v-if="update.checked_at" depth="3" style="font-size: 13px">
            上次检查:{{ twTime(update.checked_at) }}(每天自动检查一次,只读取 GitHub 公开的版本信息,不会传出学校资料)
          </n-text>
        </n-space>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="学校信息" data-testid="school-card">
      <n-space vertical>
        <n-text depth="3">
          校名会显示在介面、导出的课表(Excel / PDF / PNG)、代课通知信与 A4 公告单上。
          改完立即生效,不需重新启动。
        </n-text>
        <n-space align="center">
          <n-text style="width: 72px">校名</n-text>
          <n-input
            v-model:value="schoolName" placeholder="如:杭州市育英初级中学"
            style="width: 280px" data-testid="school-name"
          />
          <n-button
            type="primary" :loading="savingSchool" data-testid="school-save"
            @click="onSaveSchool"
          >
            储存
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="钉钉通知" data-testid="dingtalk-card">
      <n-space vertical>
        <n-text depth="3">
          在钉钉群里添加「自定义机器人」(群设置 → 机器人),安全设置选「加签」,
          把机器人的 Webhook 地址与加签密钥粘贴到这里。之后教师请假、调课、代课的
          通知会同步推送到群里(站内通知与邮件不受影响)。清空 Webhook 即可停用。
        </n-text>
        <n-space align="center">
          <n-text style="width: 72px">Webhook</n-text>
          <n-input
            v-model:value="dingtalk.webhook" placeholder="https://oapi.dingtalk.com/robot/send?access_token=…"
            style="width: 460px" data-testid="dingtalk-webhook"
          />
        </n-space>
        <n-space align="center">
          <n-text style="width: 72px">加签密钥</n-text>
          <n-input
            v-model:value="dingtalk.secret" type="password" show-password-on="click"
            :placeholder="dingtalkHasSecret ? '已设置(留空不变更)' : 'SEC 开头的加签密钥,可留空'"
            style="width: 460px" data-testid="dingtalk-secret"
          />
          <n-button :loading="testingDingtalk" data-testid="dingtalk-test" @click="onTestDingtalk">
            发送测试消息
          </n-button>
          <n-button
            type="primary" :loading="savingDingtalk" data-testid="dingtalk-save"
            @click="onSaveDingtalk"
          >
            保存
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin() && demoAvailable" title="示范资料" data-testid="demo-card">
      <n-space vertical>
        <n-text depth="3">
          一键建立一所完整的示范初中「{{ demoSchool || '示范初中' }}」,让你不必先手 key
          资料就能试用全部功能:三个年级共 18 班(7年级1班~9年级6班)、
          57 位教师(含班主任、兼行政)、14 个科目、246 笔配课,
          以及专科教室与场地。建好后可直接到「自动排课」试跑。
        </n-text>
        <n-alert type="warning" :show-icon="false">
          仅限「全新、尚未建立任何学期」的系统。示范资料是虚构的,
          <strong>请勿在正式使用的系统上载入</strong>。
        </n-alert>
        <div>
          <n-button
            type="primary" :loading="loadingDemo"
            data-testid="demo-load" @click="onLoadDemo"
          >
            载入示范资料
          </n-button>
        </div>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="通知信件(SMTP)" data-testid="smtp-card">
      <n-space vertical>
        <n-space align="center">
          <n-text depth="3">
            设置后,调代课通知除站内外会加寄 Email;未设置时系统照常运作,仅站内通知。
          </n-text>
          <n-tag :type="configured ? 'success' : 'default'" data-testid="smtp-status">
            {{ configured ? '已设置' : '未设置' }}
          </n-tag>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">主机</n-text>
          <n-input
            v-model:value="smtp.host" placeholder="smtp.example.com" style="width: 220px"
            data-testid="smtp-host"
          />
          <n-text>连接埠</n-text>
          <n-input-number v-model:value="smtp.port" :min="1" :max="65535" style="width: 110px" />
          <n-checkbox v-model:checked="smtp.use_tls">使用 TLS</n-checkbox>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">寄件人</n-text>
          <n-input
            v-model:value="smtp.sender" placeholder="noreply@school.edu.tw"
            style="width: 220px" data-testid="smtp-sender"
          />
          <n-text>帐号</n-text>
          <n-input v-model:value="smtp.user" placeholder="(选填)" style="width: 160px" />
          <n-text>密码</n-text>
          <n-input
            v-model:value="smtp.password" type="password"
            :placeholder="hasPassword ? '(已设置,留空不变更)' : '(选填)'" style="width: 160px"
          />
        </n-space>
        <div>
          <n-button
            type="primary" :loading="savingSmtp" data-testid="smtp-save" @click="onSaveSmtp"
          >
            储存 SMTP 设置
          </n-button>
        </div>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="资料备份与还原" data-testid="backup-card">
      <n-space vertical>
        <n-space align="center">
          <n-text depth="3">
            每日凌晨自动备份(保留 30 份);也可立即备份、下载保存,或上传备份档还原。
            还原前系统会自动先备份现状,还原后所有人需重新登录。
          </n-text>
        </n-space>
        <n-space align="center">
          <n-button
            type="primary" :loading="busy" data-testid="backup-now" @click="onCreateBackup"
          >
            立即备份
          </n-button>
          <n-upload
            :custom-request="onUploadRestore" :show-file-list="false" accept=".dump"
            :disabled="busy"
          >
            <n-button :disabled="busy" data-testid="backup-upload">上传备份档并还原</n-button>
          </n-upload>
        </n-space>

        <n-text v-if="!backups.length" depth="3">尚无备份。</n-text>
        <table v-else class="data-table" data-testid="backup-table">
          <thead>
            <tr><th>时间</th><th>来源</th><th>大小</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="b in backups" :key="b.name" data-testid="backup-row">
              <td>{{ new Date(b.created_at).toLocaleString('zh-TW', { hour12: false }) }}</td>
              <td><n-tag size="small">{{ b.reason_label }}</n-tag></td>
              <td>{{ humanSize(b.size_bytes) }}</td>
              <td>
                <n-space size="small">
                  <n-button size="tiny" @click="downloadBackup(b.name)">下载</n-button>
                  <n-popconfirm @positive-click="() => onRestore(b.name)">
                    <template #trigger>
                      <n-button size="tiny" type="warning" data-testid="backup-restore">
                        还原
                      </n-button>
                    </template>
                    还原将覆盖目前所有资料(现状会先自动备份),确定?
                  </n-popconfirm>
                  <n-popconfirm @positive-click="() => onDeleteBackup(b.name)">
                    <template #trigger>
                      <n-button size="tiny" tertiary>删除</n-button>
                    </template>
                    确定删除此备份?
                  </n-popconfirm>
                </n-space>
              </td>
            </tr>
          </tbody>
        </table>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="排课设置" data-testid="scheduling-card">
      <n-space vertical>
        <n-text depth="3">
          超课时上限依各县市/各校规定自订。上限是「应授节数 + N」——应授本身因身分而异
          (例:语文专任 12 节、兼任班主任 10 节、兼任主任 6 节),固定值对谁都不合适。
        </n-text>
        <n-space align="center">
          <span>超课时上限</span>
          <n-input-number
            v-model:value="maxOvertime" :min="0" :max="20" style="width: 120px"
            data-testid="max-overtime"
          />
          <n-text depth="3">节(0 = 不限制)</n-text>
        </n-space>
        <n-text depth="3" style="font-size: 12px">
          超过上限的配课会被挡下。未填「基本课时」的教师不受此限——那代表资料尚未建立,
          而非真的不用上课。
        </n-text>
        <div>
          <n-button
            type="primary" :loading="savingScheduling" data-testid="scheduling-save"
            @click="onSaveScheduling"
          >
            储存排课设置
          </n-button>
        </div>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="巡堂表" data-testid="patrol-card">
      <n-space vertical>
        <n-text depth="3">
          印在巡堂表下方的「记录说明」。授课情形、学生学习的代码各校不同,请改成贵校的写法;
          一行一项。清空后储存会恢复默认内容。巡堂表在「今日调代课看板」打印。
        </n-text>
        <n-input
          v-model:value="patrolLegend" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }"
          maxlength="500" show-count data-testid="patrol-legend-input"
        />
        <div>
          <n-button
            type="primary" :loading="savingPatrol" data-testid="patrol-save" @click="onSavePatrol"
          >
            储存巡堂表设置
          </n-button>
        </div>
      </n-space>
    </n-card>

    <n-card title="设置精灵">
      <n-space vertical>
        <n-text depth="3">重新执行首次设置的引导流程(不会删除既有资料)。</n-text>
        <n-popconfirm @positive-click="onResetWizard">
          <template #trigger>
            <n-button>重新启动设置精灵</n-button>
          </template>
          确定重新启动设置精灵?
        </n-popconfirm>
      </n-space>
    </n-card>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
