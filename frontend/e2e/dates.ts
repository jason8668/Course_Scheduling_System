// E2E 测试日期基准:一律由「执行当日」推算,不硬编。
//
// 为什么:后端 clock.is_past_slot 以真实时钟判定节次是否已上过。日期一旦成为过去,
// 代课指派被 409 拒绝、销假不再级联——测试会在某个没人动过程序码的早晨无声转红
// (原本埋的引信是 2026-11-11)。与后端 tests/dates.py 同一套规则。

// 基准周距今至少 14 天:确保基准周的每一节都还没上过(不受执行时刻影响)。
const LEAD_DAYS = 14

function addDays(day: Date, n: number): Date {
  const out = new Date(day)
  out.setDate(out.getDate() + n)
  return out
}

/** ISO 星期:1=周一 … 7=周日(JS 的 getDay() 是 0=周日)。 */
function isoWeekday(day: Date): number {
  return day.getDay() === 0 ? 7 : day.getDay()
}

/** `day` 当天或之后、最近的指定 ISO 星期。 */
export function onOrAfter(weekday: number, day: Date): Date {
  return addDays(day, (weekday - isoWeekday(day) + 7) % 7)
}

/** yyyy-mm-dd(用本地日期栏位,避免 toISOString() 的 UTC 位移把日期倒退一天)。 */
export function iso(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

/** 基准周的周一:距今 ≥ LEAD_DAYS,且该周一到「下周三」同月。
 *
 * 同月是硬需求:代课推荐的公平计数与月结统计都以「节次那一天的月份」为范围,
 * 基准周跨月会让「本月已代 N 节」归零。与后端 tests/dates.py 的 base_monday 同规则。
 */
function baseMonday(): Date {
  let mon = onOrAfter(1, addDays(new Date(), LEAD_DAYS))
  for (let i = 0; i < 6; i += 1) {
    if (addDays(mon, 9).getMonth() === mon.getMonth()) return mon
    mon = addDays(mon, 7)
  }
  throw new Error('六周内必有一个「当周到下周三同月」的周一')
}

const monday = baseMonday()
const wednesday = addDays(monday, 2)

export const MON = iso(monday)
export const WED = iso(wednesday)                   // 请假日(多数 spec 的主角)
export const THU = iso(addDays(monday, 3))          // 无请假的对照日
export const FRI = iso(addDays(monday, 4))
export const NEXT_MON = iso(addDays(monday, 7))     // 跨周末的请假结束日
export const WED2 = iso(addDays(monday, 9))         // 下周三(调课补课日/第二张假单)

// 学期起讫:包住上面所有日子,前后留缓冲
export const SEM_START = iso(addDays(monday, -30))
export const SEM_END = iso(addDays(monday, 120))

/** 基准周里指定 ISO 星期的那一天(1=周一 … 7=周日)。给「格位在星期几就请那天的假」用。 */
export function dayOfBaseWeek(weekday: number): string {
  return iso(addDays(monday, weekday - 1))
}

/** 月结统计的查询参数,取「该请假日」所属的年月。
 *
 * 必须用请假日自己算:基准周可能跨月(周一 8/31、周三 9/2),
 * 拿别天的月份去查会查到空月份。
 */
export function statsQuery(day: string): string {
  const [year, month] = day.split('-').map(Number)
  return `&year=${year}&month=${month}`
}

/** 多数 spec 的请假日就是 WED,直接用这个。 */
export const STATS_QUERY = statsQuery(WED)

/** 介面上显示的日期格式:「2026-11-11(周三)」。 */
const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日']
export function withWeekday(day: string): string {
  const [y, m, d] = day.split('-').map(Number)
  return `${day}(周${WEEK_LABELS[isoWeekday(new Date(y, m - 1, d)) - 1]})`
}
