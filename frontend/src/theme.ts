import type { GlobalThemeOverrides } from 'naive-ui'

// 全站苹果风格:主色苹果蓝 #007AFF,底色 #F5F5F7,卡片与下拉面板半透明 +
// apple-glass.css 的 backdrop-filter 毛玻璃(圆角 16~20px)。
// 白字按钮在 #007AFF 上对比约 4:1,属 UI 组件级可接受范围(iOS 同款做法)。
export const PRIMARY = '#007AFF'
export const PRIMARY_HOVER = '#3395FF'
export const PRIMARY_PRESSED = '#0062CC'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: PRIMARY,
    primaryColorHover: PRIMARY_HOVER,
    primaryColorPressed: PRIMARY_PRESSED,
    primaryColorSuppl: PRIMARY_HOVER,
    bodyColor: '#F5F5F7',
    textColorBase: '#1D1D1F',
    borderColor: '#E5E5EA',
    dividerColor: '#E5E5EA',
    borderRadius: '16px',
    borderRadiusSmall: '12px',
    fontFamily:
      "'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Source Han Sans SC', 'Noto Sans SC', sans-serif",
  },
  Card: {
    color: 'rgba(255, 255, 255, 0.72)',
    borderRadius: '20px',
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04), 0 12px 32px -12px rgba(0, 90, 200, 0.18)',
  },
  DataTable: {
    thColor: '#EAF3FF',
    thTextColor: '#0A4DA6',
    borderColor: '#E2E8F0',
    tdColorHover: '#F2F7FF',
  },
  // Naive 的 Button 没有单一 borderRadius token,是 Tiny/Small/Medium/Large 四个;
  // Input 则有单一 borderRadius(已查 node_modules 类型定义确认)。
  Button: {
    borderRadiusTiny: '10px',
    borderRadiusSmall: '12px',
    borderRadiusMedium: '12px',
    borderRadiusLarge: '12px',
  },
  Input: { borderRadius: '12px' },
  Dialog: { borderRadius: '20px' },
  Drawer: { borderRadius: '20px' },
  Tag: { borderRadius: '8px' },
  // 日期选择器下拉面板:半透明底 + 大圆角,毛玻璃 blur 由 apple-glass.css 补。
  DatePicker: {
    panelColor: 'rgba(255, 255, 255, 0.82)',
    panelBorderRadius: '20px',
    panelTextColor: '#1D1D1F',
    itemBorderRadius: '10px',
    itemColorActive: PRIMARY,
    itemTextColorActive: '#ffffff',
    itemColorHover: 'rgba(0, 122, 255, 0.12)',
    itemColorIncluded: 'rgba(0, 122, 255, 0.12)',
  },
  Select: {
    borderRadius: '12px',
    optionColorActive: 'rgba(0, 122, 255, 0.12)',
    optionTextColorActive: PRIMARY,
    optionColorPending: 'rgba(0, 122, 255, 0.08)',
  },
  InternalSelectMenu: {
    color: 'rgba(255, 255, 255, 0.85)',
    borderRadius: '16px',
  },
  Dropdown: {
    color: 'rgba(255, 255, 255, 0.85)',
    borderRadius: '16px',
    optionColorActive: 'rgba(0, 122, 255, 0.12)',
    optionTextColorActive: PRIMARY,
  },
  Modal: {
    color: 'rgba(255, 255, 255, 0.88)',
    borderRadius: '20px',
  },
  Popover: {
    color: 'rgba(255, 255, 255, 0.85)',
    borderRadius: '16px',
    textColor: '#1D1D1F',
  },
  // 问号提示白字白底根因(Jason 2026-10-30 报):Tooltip 内部走 Popover,
  // 上面 Popover 底色被改成半透明白,但 Tooltip 默认字是白色,白字白底看不见。
  // 这里把 Tooltip 定成浅底深字,与全站毛玻璃面板一致,不再依赖默认白字。
  Tooltip: {
    color: 'rgba(255, 255, 255, 0.95)',
    textColor: '#1D1D1F',
    borderRadius: '12px',
    boxShadow: '0 12px 32px -12px rgba(0, 90, 200, 0.18), 0 1px 2px rgba(0, 0, 0, 0.04)',
  },
  Menu: {
    itemColorActiveInverted: 'rgba(255, 255, 255, 0.16)',
    itemColorActiveHoverInverted: 'rgba(255, 255, 255, 0.16)',
    itemTextColorInverted: 'rgba(255, 255, 255, 0.86)',
    itemTextColorHoverInverted: '#ffffff',
    itemTextColorActiveInverted: '#ffffff',
    itemIconColorInverted: 'rgba(255, 255, 255, 0.86)',
    arrowColorInverted: 'rgba(255, 255, 255, 0.7)',
  },
}
