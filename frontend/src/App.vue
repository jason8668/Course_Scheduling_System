<script setup lang="ts">
import {
  NConfigProvider, NDialogProvider, NGlobalStyle, NMessageProvider, zhCN, dateZhCN,
} from 'naive-ui'
import { themeOverrides } from '@/theme'
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <n-global-style />
    <!-- dialog provider 不可少:useDialog() 找不到它会在 setup 直接掷错,整页渲染不出来
         (系统管理页就是这样整片空白的)。 -->
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
