<template>
  <div class="health-card" :class="`health-card--${status}`">
    <div class="health-card__icon">{{ icon }}</div>
    <div class="health-card__body">
      <span class="health-card__name">{{ name }}</span>
      <span class="health-card__status">{{ statusText }}</span>
    </div>
    <div class="health-card__indicator">
      <span class="health-card__dot" />
    </div>
    <div v-if="detail" class="health-card__detail">{{ detail }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  name: string
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
  detail?: string
  icon?: string
}>()

const statusText = computed(() => {
  const map: Record<string, string> = {
    healthy: '运行正常',
    degraded: '性能降级',
    unhealthy: '服务异常',
    unknown: '检测中...',
  }
  return map[props.status] || '未知'
})
</script>

<style scoped>
.health-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 16px 18px;
  border: 1px solid var(--kb-border-light);
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all var(--kb-duration) var(--kb-ease);
  position: relative;
  overflow: hidden;
}

.health-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  border-radius: var(--kb-radius) var(--kb-radius) 0 0;
  background: var(--kb-text-tertiary);
  opacity: 0.3;
  transition: all var(--kb-duration) var(--kb-ease);
}

.health-card--healthy::before { background: var(--kb-success); opacity: 1; }
.health-card--degraded::before { background: var(--kb-warning); opacity: 1; }
.health-card--unhealthy::before { background: var(--kb-danger); opacity: 1; }

.health-card__icon {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.health-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.health-card__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--kb-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.health-card__status {
  font-size: 12px;
  font-weight: 500;
}

.health-card--healthy .health-card__status { color: var(--kb-success); }
.health-card--degraded .health-card__status { color: var(--kb-warning); }
.health-card--unhealthy .health-card__status { color: var(--kb-danger); }
.health-card--unknown .health-card__status { color: var(--kb-text-tertiary); }

.health-card__indicator {
  flex-shrink: 0;
}

.health-card__dot {
  display: block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--kb-text-tertiary);
}

.health-card--healthy .health-card__dot {
  background: var(--kb-success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
}

.health-card--degraded .health-card__dot {
  background: var(--kb-warning);
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.5);
}

.health-card--unhealthy .health-card__dot {
  background: var(--kb-danger);
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.5);
}

.health-card__detail {
  position: absolute;
  bottom: 4px;
  right: 12px;
  font-size: 10px;
  color: var(--kb-text-tertiary);
}
</style>
