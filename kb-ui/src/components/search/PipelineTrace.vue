<template>
  <div class="pipeline-trace">
    <div class="pipeline-trace__stages">
      <div
        v-for="stage in stages"
        :key="stage.name"
        class="pipeline-trace__stage"
        :class="{ 'pipeline-trace__stage--error': !!stage.error }"
      >
        <div class="pipeline-trace__bar-wrap">
          <div
            class="pipeline-trace__bar"
            :style="{ width: barWidth(stage.duration_ms) + '%' }"
          />
        </div>
        <div class="pipeline-trace__info">
          <span class="pipeline-trace__name">{{ stage.name }}</span>
          <span class="pipeline-trace__duration">{{ formatMs(stage.duration_ms) }}</span>
        </div>
        <div class="pipeline-trace__summary" v-if="stage.summary">
          {{ stage.summary }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { SearchDebugStage } from '@/types'

const props = defineProps<{
  stages: SearchDebugStage[]
}>()

const maxDuration = Math.max(...props.stages.map(s => s.duration_ms), 1)

function barWidth(ms: number): number {
  return Math.max(3, (ms / maxDuration) * 100)
}

function formatMs(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
</script>

<style scoped>
.pipeline-trace {
  padding: 4px 0;
}

.pipeline-trace__stages {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pipeline-trace__stage {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pipeline-trace__bar-wrap {
  width: 120px;
  height: 8px;
  background: var(--kb-border-light);
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
}

.pipeline-trace__bar {
  height: 100%;
  background: linear-gradient(90deg, var(--kb-accent), var(--kb-accent-light));
  border-radius: 4px;
  transition: width 0.3s ease;
}

.pipeline-trace__stage--error .pipeline-trace__bar {
  background: var(--kb-danger);
}

.pipeline-trace__info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 160px;
}

.pipeline-trace__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.pipeline-trace__duration {
  font-size: 11px;
  font-weight: 500;
  color: var(--kb-accent);
  font-variant-numeric: tabular-nums;
}

.pipeline-trace__stage--error .pipeline-trace__duration {
  color: var(--kb-danger);
}

.pipeline-trace__summary {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
