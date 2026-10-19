// Excel 导入 API:范本下载、上传导入。

export type ImportEntity = 'subjects' | 'teachers' | 'classes' | 'assignments'

export interface ImportResult {
  imported: number
  updated: number // 更新既有教师的笔数
  errors: string[]
}

export const ENTITY_LABELS: Record<ImportEntity, string> = {
  subjects: '科目',
  teachers: '教师',
  classes: '班级',
  assignments: '配课',
}

/** 下载范本档并触发浏览器储存。 */
export async function downloadTemplate(entity: ImportEntity): Promise<void> {
  const resp = await fetch(`/api/import/templates/${entity}`, { credentials: 'include' })
  if (!resp.ok) throw new Error('范本下载失败')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${entity}_template.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

/** 上传 Excel 档导入。回传导入结果(含错误清单)。 */
export async function uploadImport(
  entity: ImportEntity,
  semesterId: number,
  file: File,
  createAccounts = false,
  updateExisting = false,
): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  let url = `/api/import/${entity}?semester_id=${semesterId}`
  if (createAccounts) url += '&create_accounts=true'
  if (updateExisting) url += '&update_existing=true'
  const resp = await fetch(url, { method: 'POST', credentials: 'include', body: form })
  if (!resp.ok) {
    let detail = '导入失败'
    try {
      detail = (await resp.json())?.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<ImportResult>
}
