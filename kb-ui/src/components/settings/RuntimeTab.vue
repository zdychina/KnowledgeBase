<template>
  <div class="runtime-tab">
    <div class="runtime-tab__grid">
      <section class="settings-card">
        <h3 class="card-heading">当前接入状态</h3>
        <div class="runtime-status">
          <div v-for="item in observationCards" :key="item.title" class="obs-card">
            <div class="obs-card__top">
              <strong class="obs-card__title">{{ item.title }}</strong>
              <span class="obs-card__mode">{{ item.mode }}</span>
            </div>
            <span class="obs-card__summary">{{ item.summary }}</span>
          </div>
        </div>
      </section>

      <section class="settings-card">
        <div class="card-heading-row">
          <h3 class="card-heading">前端兼容配置</h3>
          <el-button text size="small" @click="emit('checkHealth')">刷新健康检查</el-button>
        </div>
        <div class="health-grid">
          <div class="health-row" v-for="svc in serviceList" :key="svc.name">
            <div class="health-row__body">
              <span class="health-row__name">{{ svc.name }}</span>
              <span class="health-row__url">{{ svc.url }}</span>
            </div>
            <span class="health-row__badge" :class="`health-row__badge--${svc.status}`">
              {{ healthLabel(svc.status) }}
            </span>
          </div>
        </div>
      </section>
    </div>

    <section class="settings-card">
      <h3 class="card-heading">主系统 / 当前运行差异</h3>
      <el-table :data="diffItems" class="kb-table" :header-cell-style="{ background: 'transparent' }">
        <el-table-column prop="field" label="字段" min-width="220">
          <template #default="{ row }">
            <span class="text-mono">{{ row.field }}</span>
          </template>
        </el-table-column>
        <el-table-column label="主系统值" min-width="220">
          <template #default="{ row }">
            <code>{{ renderValue(row.control_plane_value) }}</code>
          </template>
        </el-table-column>
        <el-table-column label="当前值" min-width="220">
          <template #default="{ row }">
            <code>{{ renderValue(row.observed_value) }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <span class="diff-badge" :class="row.status === 'match' ? 'diff-badge--match' : 'diff-badge--mismatch'">
              {{ row.status === 'match' ? '一致' : '待接管' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ControlPlaneDiffItem, ControlPlaneObservationPayload, DomainConfig } from '@/types'

type ServiceStatus = 'up' | 'down' | 'checking'

const props = defineProps<{
  observations: ControlPlaneObservationPayload | null
  diffItems: ControlPlaneDiffItem[]
  currentConfig: DomainConfig
}>()

const emit = defineEmits<{
  checkHealth: []
}>()

const services = ref([
  { name: '挖掘服务', key: 'miningApi', status: 'checking' as ServiceStatus },
  { name: '检索服务', key: 'servingApi', status: 'checking' as ServiceStatus },
  { name: 'LLM服务', key: 'llmApi', status: 'checking' as ServiceStatus },
])

const serviceList = computed(() =>
  services.value.map(s => ({
    ...s,
    url: props.currentConfig[s.key as keyof DomainConfig] as string,
  }))
)

const observationCards = computed(() => {
  const payload = props.observations
  if (!payload) return []
  return [
    {
      title: 'Knowledge Mining',
      mode: String(payload.knowledge_mining?.current_config_source || 'unknown'),
      summary: `default channel = ${String(payload.knowledge_mining?.default_channel || '-')} / 本阶段未切换配置源`,
    },
    {
      title: 'Agent Serving Java',
      mode: String(payload.agent_serving_java?.current_config_source || 'unknown'),
      summary: `llm_service_url = ${String(payload.agent_serving_java?.llm_service_url || '-')} / 本阶段未切换配置源`,
    },
    {
      title: 'LLM Service',
      mode: String(payload.llm_service?.current_config_source || 'unknown'),
      summary: `embedding = ${String(payload.llm_service?.embedding_model || '-')} / 本阶段未切换配置源`,
    },
  ]
})

function renderValue(value: unknown) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function healthLabel(s: ServiceStatus) {
  if (s === 'up') return '正常'
  if (s === 'down') return '不可用'
  return '检测中'
}

function updateHealthStatus(statuses: ServiceStatus[]) {
  statuses.forEach((s, i) => {
    if (services.value[i]) services.value[i].status = s
  })
}

defineExpose({ updateHealthStatus, services })
</script>

<style scoped>
.runtime-tab {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.runtime-tab__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.settings-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  border: 1px solid var(--kb-border-light);
  box-shadow: var(--kb-shadow-card);
  padding: 18px 20px;
}

.card-heading {
  margin: 0 0 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.card-heading-row .card-heading {
  margin: 0;
}

/* Observation cards */
.runtime-status {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.obs-card {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  background: #fff;
}

.obs-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.obs-card__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.obs-card__mode {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
}

.obs-card__summary {
  font-size: 12px;
  color: var(--kb-text-secondary);
  line-height: 1.5;
}

/* Health cards */
.health-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.health-row {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  position: relative;
  overflow: hidden;
}

.health-row::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--kb-text-tertiary);
  opacity: 0.15;
}

.health-row--up::before { background: var(--kb-success); opacity: 1; }

.health-row__body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.health-row__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.health-row__url {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  word-break: break-all;
}

.health-row__badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.health-row__badge--up {
  background: rgba(16, 185, 129, 0.1);
  color: var(--kb-success);
}

.health-row__badge--down {
  background: rgba(239, 68, 68, 0.08);
  color: var(--kb-danger);
}

.health-row__badge--checking {
  background: rgba(100, 116, 139, 0.08);
  color: var(--kb-text-tertiary);
}

/* Diff badges */
.diff-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.diff-badge--match {
  background: rgba(16, 185, 129, 0.1);
  color: var(--kb-success);
}

.diff-badge--mismatch {
  background: rgba(245, 158, 11, 0.1);
  color: var(--kb-warning);
}

/* Code */
code {
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  font-size: 12px;
  color: var(--kb-text-secondary);
}

.text-mono {
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  font-size: 12px;
  color: var(--kb-text-primary);
}

@media (max-width: 1280px) {
  .runtime-tab__grid {
    grid-template-columns: 1fr;
  }
}
</style>
