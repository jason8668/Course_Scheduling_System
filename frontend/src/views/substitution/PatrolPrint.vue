<script setup lang="ts">
// 巡堂表打印页(v1.2.12),A4 横式。版面照使用学校的纸本:
//   巡堂纪录:班级为栏、节次为列,一天分上午/下午各一张;科目/教师/教室/备注由系统带出
//             (已套用当天的调代课),授课情形、学生学习、巡堂签名留白手写。
//   分组巡堂单:社团这类大型跑班群组另列清单(一列一组),一张 A4 并排两份。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getPatrolSheets } from '@/api/substitutionLog'
import type { PatrolGroupList, PatrolSheets } from '@/api/substitutionLog'

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const route = useRoute()
const data = ref<PatrolSheets | null>(null)
const error = ref('')
const loading = ref(true)

/** 「2026年9月29日 星期二」:纸本用公元年 */
function dateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  const weekday = new Date(y, m - 1, d).getDay()
  return `${y}年${m}月${d}日　星期${WEEKDAYS[(weekday + 6) % 7]}`
}

function range(first: number, last: number): string {
  return first === last ? `第 ${first} 节` : `第 ${first}~${last} 节`
}

/** 分组巡堂单两份一页(社团常连上两节,刚好并排) */
const listPairs = computed(() => {
  const lists = data.value?.group_lists ?? []
  const out: PatrolGroupList[][] = []
  for (let i = 0; i < lists.length; i += 2) out.push(lists.slice(i, i + 2))
  return out
})

const legendLines = computed(() => (data.value?.legend ?? '').split('\n').filter(Boolean))
const total = computed(() => (data.value?.pages.length ?? 0) + listPairs.value.length)

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  const from = String(route.query.from ?? '')
  const to = String(route.query.to ?? from)
  try {
    data.value = await getPatrolSheets(sid, from, to)
  } catch (e) {
    error.value = (e as ApiError).message || '无法产生巡堂表'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="patrol">
    <div class="no-print toolbar">
      <span v-if="data" class="hint">共 {{ total }} 页(A4 横式)</span>
      <button type="button" data-testid="patrol-print" @click="doPrint">打印</button>
      <button type="button" @click="doClose">关闭</button>
    </div>

    <p v-if="loading" class="msg">载入中…</p>
    <p v-else-if="error" class="msg" data-testid="patrol-error">{{ error }}</p>

    <section v-for="(page, i) in data?.pages ?? []" :key="`p${i}`" class="page" data-testid="patrol-page">
      <h1 class="title">
        <span class="school">{{ data?.title }}巡堂纪录</span>
        <span>{{ dateLabel(page.date) }}</span>
        <span>{{ range(page.first_ordinal, page.last_ordinal) }}</span>
        <span v-if="page.table_name" class="table-name">({{ page.table_name }})</span>
      </h1>

      <table class="grid">
        <colgroup>
          <col style="width: 3%">
          <col style="width: 7%">
          <col v-for="c in page.classes" :key="c">
          <col style="width: 5%">
        </colgroup>
        <thead>
          <tr>
            <th>节次</th>
            <th />
            <th v-for="c in page.classes" :key="c" data-testid="patrol-class">{{ c }}</th>
            <th>巡堂<br>签名</th>
          </tr>
        </thead>
        <tbody v-for="row in page.rows" :key="row.ordinal" class="period">
          <tr class="lesson">
            <td rowspan="5" class="ordinal">{{ row.ordinal }}</td>
            <td class="label">科目<br>教师</td>
            <td v-for="(cell, k) in row.cells" :key="k" data-testid="patrol-cell">
              <div class="subject">{{ cell.subject }}</div>
              <div class="teacher">{{ cell.teacher }}</div>
            </td>
            <td rowspan="5" />
          </tr>
          <tr class="blank">
            <td class="label">教室</td>
            <td v-for="(cell, k) in row.cells" :key="k">{{ cell.room }}</td>
          </tr>
          <tr class="blank">
            <td class="label">授课情形</td>
            <td v-for="k in row.cells.length" :key="k" />
          </tr>
          <tr class="blank">
            <td class="label">学生学习</td>
            <td v-for="k in row.cells.length" :key="k" />
          </tr>
          <tr class="blank">
            <td class="label">备注</td>
            <td v-for="(cell, k) in row.cells" :key="k" class="note" data-testid="patrol-note">{{ cell.note }}</td>
          </tr>
        </tbody>
      </table>

      <table class="foot">
        <tr>
          <td class="foot-label">记录<br>说明</td>
          <td class="legend" data-testid="patrol-legend">
            <div v-for="(line, k) in legendLines" :key="k">{{ line }}</div>
          </td>
          <td class="foot-label">注记事项</td>
          <td class="remarks" />
        </tr>
      </table>
    </section>

    <section v-for="(pair, i) in listPairs" :key="`g${i}`" class="page lists">
      <div v-for="(list, k) in pair" :key="k" class="list" data-testid="patrol-group-list">
        <div class="list-school">{{ data?.title }}</div>
        <h1 class="title list-title">
          <span class="school">{{ list.group_name }}巡堂单</span>
          <span>{{ dateLabel(list.date) }}</span>
          <span>{{ list.period_name }}</span>
        </h1>
        <table class="grid">
          <colgroup>
            <col style="width: 8%"><col style="width: 22%"><col style="width: 18%">
            <col style="width: 20%"><col style="width: 16%"><col style="width: 16%">
          </colgroup>
          <thead>
            <tr><th>编号</th><th>名称</th><th>教师</th><th>地点</th><th>上课状况</th><th>学生表现</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in list.items" :key="item.no" class="list-row" data-testid="patrol-group-item">
              <td>{{ item.no }}</td>
              <td>{{ item.subject }}</td>
              <td>{{ item.teacher }}<template v-if="item.note"><br>({{ item.note }})</template></td>
              <td>{{ item.room }}</td>
              <td />
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.patrol {
  color: #000;
  background: #fff;
  font-family: "DFKai-SB", "BiauKai", "标楷体", "Kaiti TC", serif;
}
.toolbar { display: flex; gap: 8px; justify-content: flex-end; align-items: center; padding: 16px 24px 0; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.hint { color: #555; font-size: 14px; }
.msg { text-align: center; padding: 40px 0; font-size: 15px; }
.page { max-width: 1120px; margin: 0 auto; padding: 24px; }
.page + .page { border-top: 1px dashed #bbb; }
.title {
  display: flex; gap: 18px; align-items: baseline; margin: 0 0 6px;
  font-size: 16px; font-weight: normal;
}
.title .school { font-size: 19px; font-weight: bold; }
.table-name { font-size: 13px; }
.grid { width: 100%; border-collapse: collapse; table-layout: fixed; border: 2px solid #000; }
.grid th, .grid td {
  border: 1px solid #000; text-align: center; vertical-align: middle;
  font-size: 12px; line-height: 1.25; padding: 1px 2px; overflow-wrap: anywhere;
}
.grid th { font-weight: normal; font-size: 14px; height: 30px; }
tbody.period { border-top: 2px solid #000; }
.ordinal { font-size: 16px; }
.label { font-size: 12px; }
tr.lesson td { height: 40px; }
tr.blank td { height: 22px; }
.subject { font-size: 12px; }
.teacher { font-size: 12px; }
.note { font-size: 11px; }
.foot { width: 100%; border-collapse: collapse; border: 2px solid #000; border-top: none; }
.foot td { border: 1px solid #000; font-size: 12px; padding: 3px 6px; vertical-align: middle; }
.foot-label { width: 6%; text-align: center; white-space: nowrap; }
.legend { width: 52%; line-height: 1.5; }
.remarks { height: 62px; }

/* 分组巡堂单:一张 A4 横式并排两份 */
.lists { display: flex; gap: 32px; align-items: flex-start; }
.list { flex: 1; min-width: 0; }
.list-title { flex-wrap: wrap; row-gap: 2px; }
.list-school { font-size: 13px; margin-bottom: 2px; }
.list-row td { height: 38px; font-size: 13px; }

@media print {
  @page { size: A4 landscape; margin: 9mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; break-after: page; }
  .page + .page { border-top: none; }
  .page:last-child { break-after: auto; }
  tbody.period, .list-row { break-inside: avoid; }
}
</style>
