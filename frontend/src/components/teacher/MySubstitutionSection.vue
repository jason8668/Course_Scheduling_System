<script setup lang="ts">
import { NEmpty, NText } from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { getMyStats } from '@/api/substitutionStats'
import type { MonthlyReport } from '@/api/substitutionStats'

// 原仪表板「我的代课」节,2026-10-30 Jason 定搬到调课管理(请假登记)页。
// 只给教师本人看:代课月结是个人数据,管理员在调课管理页看的是全校调课,
// 不需要在这里再看自己一个人的月结。
const props = defineProps<{ semesterId: number }>()
const stats = ref<MonthlyReport | null>(null)

async function load() {
  const now = new Date()
  const r = await getMyStats(props.semesterId, now.getFullYear(), now.getMonth() + 1)
    .catch(() => null)
  // 统计接口形状不对时不要把数组/异常值塞进 stats,否则模板取 summaries[0] 会崩。
  stats.value = r && Array.isArray((r as MonthlyReport).summaries) ? r : null
}
onMounted(() => { void load() })
watch(() => props.semesterId, () => { void load() })
</script>

<template>
  <section class="ios-section" data-testid="my-substitution-section">
    <div class="ios-section-title">
      <span>我的代课</span>
    </div>
    <div class="ios-card">
      <n-empty v-if="!stats" description="暂无本月代课统计" style="padding: 24px 0" />
      <template v-else>
        <div class="ios-card-body">
          <n-text style="font-size: 15px">
            本月我代别人：{{ stats.summaries[0]?.handled_count ?? 0 }} 节
            （计入课时 {{ stats.summaries[0]?.billable_count ?? 0 }} 节）
          </n-text>
          <div class="ios-row-sub" style="margin-top: 2px">
            被代课的情况在上方请假记录里看：每单的影响节次会显示代课人。
          </div>
        </div>
        <div v-for="(d, i) in stats.details" :key="i" class="ios-row">
          <span style="font-size: 13px">
            {{ d.date }} {{ d.period_name }} · {{ d.class_names }}《{{ d.subject_name }}》
            · 代 {{ d.absent_teacher_name }}老师的课
          </span>
        </div>
      </template>
    </div>
  </section>
</template>
