// 课表导出下载(M5-1)。以 fetch 取回 blob,好处理载入状态、错误与中文档名。

export type ExportFmt = 'xlsx' | 'pdf' | 'png'
export type ExportView = 'class' | 'teacher' | 'room'

function filenameFrom(cd: string | null, fallback: string): string {
  const m = cd ? /filename\*=UTF-8''([^;]+)/.exec(cd) : null
  return m ? decodeURIComponent(m[1]) : fallback
}

export async function download(path: string, fallback: string): Promise<void> {
  const resp = await fetch(`/api${path}`, { credentials: 'include' })
  if (!resp.ok) {
    let detail: string | undefined
    try { detail = (await resp.json())?.detail } catch { detail = undefined }
    throw new Error(detail || `导出失败(${resp.status})`)
  }
  const blob = await resp.blob()
  const name = filenameFrom(resp.headers.get('Content-Disposition'), fallback)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}

export const exportTimetable = (
  semesterId: number, view: ExportView, targetId: number, fmt: ExportFmt,
): Promise<void> =>
  download(
    `/export/timetable?semester_id=${semesterId}&view=${view}&target_id=${targetId}&fmt=${fmt}`,
    `课表.${fmt}`)

/** 全校总表:view=class 每班一个分页;view=teacher 每位教师一个分页 */
export const exportSchoolWorkbook = (
  semesterId: number, view: 'class' | 'teacher' = 'class',
): Promise<void> =>
  download(
    `/export/school.xlsx?semester_id=${semesterId}&view=${view}`,
    view === 'teacher' ? '全校教师课表总表.xlsx' : '全校课表总表.xlsx',
  )

/** 批次 zip:view=class 每班一个档;view=teacher 每位教师一个档 */
export const exportBatchZip = (
  semesterId: number, view: 'class' | 'teacher' = 'class',
): Promise<void> =>
  download(
    `/export/batch.zip?semester_id=${semesterId}&view=${view}`,
    view === 'teacher' ? '全校教师课表.zip' : '全校班级课表.zip',
  )
