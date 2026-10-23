// 跨节次表的格子要补上实际时间。
//
// 教师/场地课表只能照一套节次表(学期默认表)画格线。初中小、完全中学的跨部教师,
// 另一部的课会排在「同节次号」那一列,但实际时间不一样(小学 40 分、初中 45 分)。
// 不标出来,课表上的时间就是错的。

interface PeriodLike {
  weekday: number
  period_no: number
  start_time?: string | null
  end_time?: string | null
}
interface TableLike<P extends PeriodLike = PeriodLike> {
  id: number
  is_default: boolean
  periods: P[]
}
interface ClassLike {
  id: number
  period_table_id: number | null
}
interface EntryLike {
  weekday: number
  period_no: number
  class_ids: number[]
}

const hhmm = (t: string) => t.slice(0, 5)

/** 这一格所属的节次表:班级指定的那套,没指定就是学期默认表。 */
function ownTable<P extends PeriodLike>(
  entry: EntryLike, classes: ClassLike[], tables: TableLike<P>[],
): TableLike<P> | undefined {
  const fallback = tables.find((t) => t.is_default) ?? tables[0]
  const cls = classes.find((c) => entry.class_ids.includes(c.id))
  return tables.find((t) => t.id === cls?.period_table_id) ?? fallback
}

/**
 * 界面那套节次表没有、但这些格位用得到的节次列(取自格位自己的节次表)。
 *
 * 初中七节、高中八节的完全中学,跨部老师在高中第八节有课;教师课表照初中那套画只有七列,
 * 不补这一列,那堂课会整个从课表上消失。只补用得到的,没跨部的老师不会多出空列。
 */
export function extraRows<P extends PeriodLike>(
  entries: (EntryLike & { span?: number })[], classes: ClassLike[],
  tables: TableLike<P>[], shown: TableLike<P> | null,
): P[] {
  if (!shown || tables.length < 2) return []
  const have = new Set(shown.periods.map((p) => p.period_no))
  const out: P[] = []
  for (const e of entries) {
    const own = ownTable(e, classes, tables)
    if (!own || own.id === shown.id) continue
    for (let no = e.period_no; no < e.period_no + (e.span ?? 1); no++) {
      if (have.has(no)) continue
      have.add(no)
      out.push(...own.periods.filter((p) => p.period_no === no))
    }
  }
  return out
}

/** 这一格的实际上课时间;与界面那套节次表同一列的时间相同(或就是同一套)时回 undefined。 */
export function crossTableNote(
  entry: EntryLike, classes: ClassLike[], tables: TableLike[], shown: TableLike | null,
): string | undefined {
  if (!shown || tables.length < 2) return undefined
  const own = ownTable(entry, classes, tables)
  if (!own || own.id === shown.id) return undefined
  const at = (t: TableLike) =>
    t.periods.find((p) => p.weekday === entry.weekday && p.period_no === entry.period_no)
  const mine = at(own)
  if (!mine?.start_time || !mine.end_time) return undefined
  const row = at(shown)
  if (row && row.start_time === mine.start_time && row.end_time === mine.end_time) return undefined
  return `${hhmm(mine.start_time)}–${hhmm(mine.end_time)}`
}
