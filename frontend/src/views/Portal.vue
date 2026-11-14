<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

// 总主入口:只排已经建成的系统,新系统以后直接往网格里加一张卡,不改结构。
// 没建成的系统不画占位卡片。
</script>

<template>
  <div class="ios-page">
    <h1 class="ios-title">智慧教务系统</h1>
    <div class="ios-subtitle">一个账号，进各个系统</div>

    <section class="ios-section" data-testid="portal-entries">
      <div class="ios-section-title">系统入口</div>
      <div class="portal-grid">
        <div
          class="ios-card entry-card" data-testid="entry-scheduling"
          @click="router.push({ name: 'scheduling-center' })"
        >
          <div class="ios-card-body">
            <div class="ios-row-title">排课系统</div>
            <div class="ios-row-sub">开学建置、配课与排课、课表查询、调课/代课、课时统计</div>
          </div>
        </div>
        <div
          class="ios-card entry-card" data-testid="entry-exam"
          @click="router.push({ name: 'exam-students' })"
        >
          <div class="ios-card-body">
            <div class="ios-row-title">考务成绩系统</div>
            <div class="ios-row-sub">学生档案、学科分值、考号规则、考试与成绩</div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.portal-grid { display: flex; gap: 16px; flex-wrap: wrap; }
.entry-card { flex: 1; min-width: 240px; cursor: pointer; }
.entry-card:hover { box-shadow: 0 8px 24px rgba(0, 122, 255, 0.18); }
</style>
