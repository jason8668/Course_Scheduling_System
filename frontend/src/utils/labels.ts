// 班级显示名:班名已含「年级」(如 7年级1班)时直接用班名;
// 只有班序(如 1班)时补上「X年级」前缀,避免拼成「7年7年级1班」。
export function classLabel(c: { grade: number; name: string }): string {
  return c.name.includes('年级') ? c.name : `${c.grade}年级${c.name}`
}

// 学年区间显示:起始年 2026 →「2026-2027 学年」
export function academicYearLabel(year: number): string {
  return `${year}-${year + 1} 学年`
}
