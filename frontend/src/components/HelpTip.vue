<template>
  <n-tooltip trigger="hover">
    <template #trigger>
      <span class="help-tip" :data-testid="testid">?</span>
    </template>
    <slot />
  </n-tooltip>
</template>

<script setup lang="ts">
// 全站问号提示的统一写法:平时只显示一个小问号,鼠标移上去才出现说明。
// 用法:<HelpTip testid="help-xxx">这段功能是干嘛的、怎么用</HelpTip>
// 只给真正难懂的按钮/选项加,不要每个地方都挂,否则满屏问号反而没人看。
defineProps<{ testid?: string }>()
</script>
