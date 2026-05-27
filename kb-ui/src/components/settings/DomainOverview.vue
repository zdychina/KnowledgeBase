<template>
  <div class="overview-metrics">
    <div class="metric-card">
      <div class="metric-card__icon">🏷</div>
      <div class="metric-card__body">
        <span class="metric-card__label">当前 Domain</span>
        <span class="metric-card__value">{{ domain.display_name || domain.domain_id }}</span>
      </div>
      <span class="metric-card__sub">{{ domain.domain_id }}</span>
    </div>
    <div class="metric-card">
      <div class="metric-card__icon">📡</div>
      <div class="metric-card__body">
        <span class="metric-card__label">默认 Channel</span>
        <span class="metric-card__value">{{ domain.default_channel }}</span>
      </div>
      <span class="metric-card__sub">{{ domain.scenario_pack_ref || '-' }}</span>
    </div>
    <div class="metric-card">
      <div class="metric-card__icon">🔗</div>
      <div class="metric-card__body">
        <span class="metric-card__label">服务绑定</span>
        <span class="metric-card__value">{{ bindingCount }}</span>
      </div>
      <span class="metric-card__sub">{{ activeBindingNames }}</span>
    </div>
    <div class="metric-card">
      <div class="metric-card__icon">⚡</div>
      <div class="metric-card__body">
        <span class="metric-card__label">运行态差异</span>
        <span class="metric-card__value" :class="mismatchClass">{{ mismatchCount }}</span>
      </div>
      <span class="metric-card__sub">Phase 1 仅观测</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ControlPlaneDiffItem, ControlPlaneDomainDetail, ControlPlaneServiceBinding } from '@/types'

const props = defineProps<{
  domain: ControlPlaneDomainDetail
  bindings: ControlPlaneServiceBinding[]
  diffItems: ControlPlaneDiffItem[]
}>()

const bindingCount = computed(() => props.bindings.length)
const activeBindingNames = computed(() =>
  props.bindings.map(b => b.service_name).join(' / ') || '未绑定'
)
const mismatchCount = computed(() =>
  props.diffItems.filter(item => item.status === 'mismatch').length
)
const mismatchClass = computed(() => {
  if (mismatchCount.value === 0) return 'metric-card__value--good'
  if (mismatchCount.value <= 3) return 'metric-card__value--warn'
  return 'metric-card__value--bad'
})
</script>

<style scoped>
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.metric-card {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
  transition: all 180ms var(--kb-ease);
}

.metric-card:hover {
  border-color: var(--kb-accent-medium);
  box-shadow: 0 2px 8px rgba(8, 145, 178, 0.06);
}

.metric-card__icon {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.metric-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.metric-card__label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--kb-text-tertiary);
  font-weight: 600;
}

.metric-card__value {
  font-size: 18px;
  font-weight: 700;
  color: var(--kb-text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-card__value--good { color: var(--kb-success); }
.metric-card__value--warn { color: var(--kb-warning); }
.metric-card__value--bad { color: var(--kb-danger); }

.metric-card__sub {
  position: absolute;
  bottom: 6px;
  right: 14px;
  font-size: 10px;
  color: var(--kb-text-tertiary);
}

@media (max-width: 1280px) {
  .overview-metrics {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 960px) {
  .overview-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
