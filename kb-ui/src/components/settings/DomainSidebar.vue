<template>
  <aside class="sidebar">
    <div class="sidebar__card">
      <h3 class="sidebar__title">Domains</h3>

      <el-select
        :model-value="selectedDomainId"
        placeholder="选择 Domain"
        class="sidebar__select"
        size="default"
        @change="emit('select', $event)"
      >
        <el-option
          v-for="domain in domains"
          :key="domain.domain_id"
          :label="domain.display_name || domain.domain_id"
          :value="domain.domain_id"
        />
      </el-select>

      <div v-if="!domains.length" class="sidebar__empty">
        还没有配置基线
      </div>

      <div v-else class="sidebar__list">
        <button
          v-for="domain in domains"
          :key="domain.domain_id"
          type="button"
          class="domain-card"
          :class="{ 'domain-card--active': domain.domain_id === selectedDomainId }"
          @click="emit('select', domain.domain_id)"
        >
          <div class="domain-card__top">
            <span class="domain-card__name">{{ domain.display_name || domain.domain_id }}</span>
            <span class="domain-card__badge" :class="domain.enabled ? 'domain-card__badge--on' : 'domain-card__badge--off'">
              {{ domain.enabled ? '启用' : '停用' }}
            </span>
          </div>
          <div class="domain-card__meta">
            <span>{{ domain.domain_id }}</span>
            <span>{{ domain.default_channel }}</span>
          </div>
          <div class="domain-card__caps">
            <span
              v-for="cap in domain.capabilities.filter(c => c.enabled)"
              :key="cap.service_name"
              class="cap-pill"
            >{{ cap.service_name }}</span>
          </div>
        </button>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { ControlPlaneDomainSummary } from '@/types'

defineProps<{
  domains: ControlPlaneDomainSummary[]
  selectedDomainId: string
}>()

const emit = defineEmits<{
  select: [domainId: string]
}>()
</script>

<style scoped>
.sidebar__card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  border: 1px solid var(--kb-border-light);
  box-shadow: var(--kb-shadow-card);
  padding: 18px;
}

.sidebar__title {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sidebar__select {
  width: 100%;
  margin-bottom: 14px;
}

.sidebar__empty {
  padding: 40px 0;
  text-align: center;
  color: var(--kb-text-tertiary);
  font-size: 13px;
}

.sidebar__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.domain-card {
  width: 100%;
  background: #fff;
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 14px;
  text-align: left;
  cursor: pointer;
  transition: all 180ms var(--kb-ease);
  position: relative;
  overflow: hidden;
}

.domain-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--kb-text-tertiary);
  opacity: 0.15;
  transition: all 180ms var(--kb-ease);
}

.domain-card:hover {
  border-color: var(--kb-accent-medium);
  box-shadow: 0 2px 8px rgba(8, 145, 178, 0.08);
}

.domain-card--active {
  border-color: var(--kb-accent);
  background: rgba(8, 145, 178, 0.03);
}

.domain-card--active::before {
  background: var(--kb-accent);
  opacity: 1;
}

.domain-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.domain-card__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.domain-card__badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  flex-shrink: 0;
}

.domain-card__badge--on {
  background: rgba(16, 185, 129, 0.1);
  color: var(--kb-success);
}

.domain-card__badge--off {
  background: rgba(100, 116, 139, 0.1);
  color: var(--kb-text-tertiary);
}

.domain-card__meta {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: var(--kb-text-tertiary);
  font-family: 'SF Mono', 'Cascadia Code', monospace;
}

.domain-card__caps {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.cap-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-weight: 600;
}
</style>
