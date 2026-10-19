// 系统版本与新版本提醒(v1.2.3)。

import { apiGet, apiPost } from '@/api/client'

export interface UpdateStatus {
  enabled: boolean // false = 管理者在 .env 关闭了新版本检查
  current: string // 目前版本,如 v1.2.3;自行从原始码建置为 dev
  latest: string
  latest_url: string
  published_at: string
  checked_at: string
  update_available: boolean
  error: string // 最近一次查询失败的原因(例如主机不能连外)
}

export const RELEASES_URL = 'https://github.com/begin0808/Course_Scheduling_System/releases'
export const UPGRADE_GUIDE_URL =
  'https://github.com/begin0808/Course_Scheduling_System/blob/main/docs/deploy/upgrade.md'

export const getVersion = (): Promise<{ version: string }> => apiGet('/system/version')

/** 管理员专用。refresh = 「立即检查」(后端限制至少间隔一分钟) */
/** 资料表结构升级后的一次性提示(v1.3.0):升级前自动备份的档名,或备份失败的原因 */
export interface UpgradeNotice {
  version: string
  at: string
  backup: string
  error: string
}
export const getUpgradeNotice = (): Promise<UpgradeNotice | null> => apiGet('/system/upgrade-notice')
export const dismissUpgradeNotice = (): Promise<void> => apiPost('/system/upgrade-notice/dismiss')

export const getUpdateStatus = (refresh = false): Promise<UpdateStatus> =>
  apiGet(`/system/update${refresh ? '?refresh=true' : ''}`)
