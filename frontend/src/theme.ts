import type { GlobalThemeOverrides } from 'naive-ui'

// 全站视觉与登录页封面统一:深青(#082f42 → #0d5a6e → #117a8f 渐变同源)。
// 主色 #0d5a6e 配白字对比 ≈ 7.4:1(通过 WCAG AA);hover #117a8f ≈ 4.9:1 亦达标。
export const PRIMARY = '#0d5a6e'
export const PRIMARY_HOVER = '#117a8f'
export const PRIMARY_PRESSED = '#082f42'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: PRIMARY,
    primaryColorHover: PRIMARY_HOVER,
    primaryColorPressed: PRIMARY_PRESSED,
    primaryColorSuppl: PRIMARY_HOVER,
    bodyColor: '#f2f6f7',
    borderRadius: '8px',
    borderRadiusSmall: '6px',
    fontFamily:
      "'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Source Han Sans SC', 'Noto Sans SC', sans-serif",
  },
  Card: {
    borderRadius: '12px',
    boxShadow: '0 1px 2px rgba(8, 47, 66, 0.05), 0 10px 28px -14px rgba(8, 47, 66, 0.16)',
  },
  DataTable: {
    thColor: '#e9f2f4',
    thTextColor: '#0b4257',
    borderColor: '#dde7ea',
    tdColorHover: '#f4f8f9',
  },
  // Naive 的 Button 没有单一 borderRadius token,是 Tiny/Small/Medium/Large 四个;
  // Input 则有单一 borderRadius(已查 node_modules 类型定义确认)。
  Button: {
    borderRadiusTiny: '8px',
    borderRadiusSmall: '8px',
    borderRadiusMedium: '8px',
    borderRadiusLarge: '8px',
  },
  Input: { borderRadius: '8px' },
  Dialog: { borderRadius: '12px' },
  Drawer: { borderRadius: '12px' },
  Tag: { borderRadius: '6px' },
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
