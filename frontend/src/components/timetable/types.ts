// TimetableGrid 元件的共用型别。此元件为纯展示+事件元件,不含商业逻辑:
// 拖曳中的内容、冲突判定、放下结果一律由父层决定并以 props/events 沟通。

export interface PeriodCell {
  weekday: number // 1=周一 …
  period_no: number // 当日节次顺序(含休息时段)
  name: string // 显示名称,如「第一节」「午休」
  type: string // 'regular'(可排课)| morning/lunch/homeroom/reserved(反灰)
  start_time?: string | null // 'HH:MM' 或 'HH:MM:SS'
  end_time?: string | null
}

export interface GridEntry {
  id: number | string
  weekday: number
  period_no: number
  subject: string
  teacher?: string
  room?: string
  note?: string // 补充说明,如跨节次表的实际上课时间「11:10–11:50」
  locked?: boolean
  span?: number // 连堂长度(占用连续节数),默认 1
  // 单双周(v1.3.0):'单' / '双'。同一格有单周、双周两堂时,格子里上下各列一行
  week?: '单' | '双'
}

// 拖曳中的内容(对元件不透明,仅用于回传给父层决策)
export interface DragData {
  source: 'tray' | 'grid'
  entryId?: number | string
  [k: string]: unknown
}

export interface DropTarget {
  weekday: number
  period_no: number
}

// 父层在拖曳过程回填的可放/冲突判定,元件据此渲染绿框/红框与原因
export interface DropFeedback extends DropTarget {
  ok: boolean
  reason?: string
}

export interface DragEventPayload extends DropTarget {
  data: DragData | null
}
