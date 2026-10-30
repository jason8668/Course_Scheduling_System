<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

// 「我的」已并进仪表板(2026-10-30 Jason 定),本页只作跳转兜底:
// 路由 /my 本身已重定向到仪表板,本文件不再被路由加载,留着只是为了
// 让旧文件在仓库里被覆盖掉,不留一份没人引用的旧整页代码。
const router = useRouter()
onMounted(() => { router.replace({ name: 'dashboard' }) })
</script>

<template>
  <div />
</template>
