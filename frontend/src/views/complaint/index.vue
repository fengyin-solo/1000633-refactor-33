<template>
  <section class="page" data-module="complaint">
    <header class="page-head">
      <div>
        <h2>投诉处理管理</h2>
        <p class="page-desc">维护投诉记录，围绕投诉编号、投诉单位、投诉事由、涉及样品做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记投诉记录</button>
        <button class="btn" type="button" @click="exportRows">导出投诉处理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无投诉处理数据，可先登记投诉记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条投诉处理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/complaint'
const columns = ["投诉编号", "投诉单位", "投诉事由", "涉及样品", "受理人员", "处理措施", "处理期限", "投诉状态"]
const actionsByStatus: Record<string, string[]> = {
  待受理: ["受理投诉"],
  处理中: ["提交回复"],
  已回复: ["关闭投诉"],
  已关闭: [],
}
const statuses = ["待受理", "处理中", "已回复", "已关闭"]
const stats = [{"label": "待受理投诉", "value": 0}, {"label": "处理中投诉", "value": 0}, {"label": "本月关闭数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '投诉记录登记入口尚未接入审批流'
}

function availableActions(row: Row): string[] {
  return actionsByStatus[String(row.status ?? '')] ?? []
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '提交回复') {
    const measure = window.prompt('请输入处理措施与回复内容')
    if (measure === null) {
      return
    }
    if (!measure.trim()) {
      errorMessage.value = '缺少必填字段：处理措施'
      return
    }
    values['处理措施'] = measure.trim()
    values['回复内容'] = measure.trim()
  }

  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.detail ?? payload?.message ?? '投诉处理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '投诉处理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('投诉记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '投诉处理列表读取失败'
  }
}

onMounted(reload)
</script>
