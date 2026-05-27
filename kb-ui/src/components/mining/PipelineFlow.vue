<template>
  <div class="pipeline-flow">
    <div
      v-for="(stage, idx) in stages"
      :key="stage.key"
      class="pipeline-stage"
      :class="[`pipeline-stage--${getStageStatus(stage.key)}`]"
    >
      <div class="pipeline-stage__node">
        <span class="pipeline-stage__icon">{{ stageIcons[stage.key] || '⚙' }}</span>
      </div>
      <div class="pipeline-stage__info">
        <span class="pipeline-stage__name">{{ stage.label }}</span>
        <span class="pipeline-stage__meta">
          <template v-if="getStageStatus(stage.key) === 'completed'">
            {{ formatMs(getStageDuration(stage.key)) }}
          </template>
          <template v-else-if="getStageStatus(stage.key) === 'running'">
            运行中...
          </template>
          <template v-else-if="getStageStatus(stage.key) === 'failed'">
            失败
          </template>
          <template v-else>
            等待中
          </template>
        </span>
      </div>
      <div v-if="idx < stages.length - 1" class="pipeline-stage__connector" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { MiningRunStage } from '@/types'

const props = defineProps<{
  stageEvents: MiningRunStage[]
}>()

interface PipelineStage {
  key: string
  label: string
  backendKeys: string[]
}

const stages: PipelineStage[] = [
  { key: 'parse', label: '解析', backendKeys: ['parse'] },
  { key: 'segment', label: '分段', backendKeys: ['segment'] },
  { key: 'enrich', label: '增强', backendKeys: ['enrich'] },
  { key: 'discourse', label: '语篇分析', backendKeys: ['discourse'] },
  { key: 'retrieval_units', label: '检索单元', backendKeys: ['retrieval_units'] },
  { key: 'embedding', label: '向量化', backendKeys: ['embedding'] },
  { key: 'db_write', label: '数据写入', backendKeys: ['db_write'] },
  { key: 'build', label: '构建&发布', backendKeys: ['assemble_build', 'validate_build', 'publish_release'] },
]

const stageIcons: Record<string, string> = {
  parse: '🔍', segment: '✂️', enrich: '🧠', discourse: '💬',
  retrieval_units: '🔎', embedding: '🔢', db_write: '💾', build: '📦',
}

function findStageEvents(stage: PipelineStage): MiningRunStage[] {
  return props.stageEvents.filter(s => stage.backendKeys.includes(s.stage))
}

function getStageStatus(key: string): string {
  const stage = stages.find(s => s.key === key)
  if (!stage) return 'pending'
  const events = findStageEvents(stage)
  if (events.length === 0) return 'pending'
  if (events.some(e => e.status === 'failed')) return 'failed'
  const started = events.filter(e => e.status === 'started')
  const completed = events.filter(e => e.status === 'completed')
  if (started.length > completed.length) return 'running'
  if (stage.backendKeys.every(bk => events.some(e => e.stage === bk && e.status === 'completed'))) return 'completed'
  if (completed.length > 0) return 'running'
  return 'pending'
}

function getStageDuration(key: string): number {
  const stage = stages.find(s => s.key === key)
  if (!stage) return 0
  return findStageEvents(stage)
    .filter(e => e.status === 'completed' && e.duration_ms != null)
    .reduce((sum, e) => sum + (e.duration_ms ?? 0), 0)
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<style scoped>
.pipeline-flow {
  display: flex;
  align-items: flex-start;
  overflow-x: auto;
  padding: 8px 0;
  gap: 0;
}

.pipeline-stage {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.pipeline-stage__node {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--kb-border);
  background: var(--kb-bg-card);
  transition: all var(--kb-duration) var(--kb-ease);
}

.pipeline-stage--completed .pipeline-stage__node {
  border-color: var(--kb-success);
  background: var(--kb-success-soft);
}

.pipeline-stage--running .pipeline-stage__node {
  border-color: var(--kb-warning);
  background: var(--kb-warning-soft);
  animation: pulse-border 1.5s ease-in-out infinite;
}

.pipeline-stage--failed .pipeline-stage__node {
  border-color: var(--kb-danger);
  background: var(--kb-danger-soft);
}

.pipeline-stage__icon {
  font-size: 16px;
}

.pipeline-stage__info {
  display: flex;
  flex-direction: column;
  margin-left: 8px;
  min-width: 70px;
}

.pipeline-stage__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.pipeline-stage__meta {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.pipeline-stage--completed .pipeline-stage__meta { color: var(--kb-success); }
.pipeline-stage--running .pipeline-stage__meta { color: var(--kb-warning); }
.pipeline-stage--failed .pipeline-stage__meta { color: var(--kb-danger); }

.pipeline-stage__connector {
  width: 24px;
  height: 2px;
  background: var(--kb-border);
  margin: 0 4px;
  align-self: center;
  flex-shrink: 0;
}

.pipeline-stage--completed + .pipeline-stage .pipeline-stage__connector,
.pipeline-stage--completed ~ .pipeline-stage__connector {
  background: var(--kb-success);
}

@keyframes pulse-border {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.3); }
  50% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); }
}
</style>
