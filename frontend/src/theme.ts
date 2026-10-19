import type { GlobalThemeOverrides } from 'naive-ui'

// 主色调深至白字对比 ≥ 4.5:1(WCAG AA 正常文字,1.4.3)。
//
// Naive 默认的 #18a058 配白字只有 ~3.4:1——那只达到 1.4.11「非文字元件」的 3:1 底线,
// 而按钮上的字就是文字。这里把主色压深到通过 AA,色相不动(仍是同一支绿),
// 整体设计不受影响。hover 是用户实际会停在上面读字的状态,同样要达标。
//
//   #0d7a43 → 5.41:1(默认)
//   #0e8449 → 4.76:1(hover;比默认亮一阶但仍达 AA)
//   #0a6337 → 7.0:1 (pressed)
export const PRIMARY = '#0d7a43'
export const PRIMARY_HOVER = '#0e8449'
export const PRIMARY_PRESSED = '#0a6337'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: PRIMARY,
    primaryColorHover: PRIMARY_HOVER,
    primaryColorPressed: PRIMARY_PRESSED,
    primaryColorSuppl: PRIMARY_HOVER,
  },
}
