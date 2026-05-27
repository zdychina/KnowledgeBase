<template>
  <div class="run-detail" v-loading="miningStore.loading">
    <div class="run-detail__back">
      <el-button text @click="$router.push('/mining')">
        <el-icon><ArrowLeft /></el-icon> 返回列表
      </el-button>
    </div>

    <template v-if="miningStore.currentRun">
      <!-- Run Meta Card -->
      <div class="run-detail__meta-card">
        <div class="run-detail__meta-left">
          <h3 class="run-detail__id">{{ miningStore.currentRun.id.slice(0, 8) }}</h3>
          <StatusBadge :status="miningStore.currentRun.status">{{ statusLabel(miningStore.currentRun.status) }}</StatusBadge>
        </div>
        <div class="run-detail__metrics">
          <div class="metric">
            <span class="metric__value">{{ miningStore.currentRun.total_documents }}</span>
            <span class="metric__label">文档</span>
          </div>
          <div class="metric" v-if="miningStore.currentRun.new_count">
            <span class="metric__value metric__value--success">{{ miningStore.currentRun.new_count }}</span>
            <span class="metric__label">新增</span>
          </div>
          <div class="metric" v-if="miningStore.currentRun.updated_count">
            <span class="metric__value metric__value--accent">{{ miningStore.currentRun.updated_count }}</span>
            <span class="metric__label">更新</span>
          </div>
          <div class="metric" v-if="miningStore.currentRun.failed_count">
            <span class="metric__value metric__value--danger">{{ miningStore.currentRun.failed_count }}</span>
            <span class="metric__label">失败</span>
          </div>
          <div class="metric">
            <span class="metric__value">{{ formatDuration(miningStore.currentRun.started_at, miningStore.currentRun.finished_at) }}</span>
            <span class="metric__label">耗时</span>
          </div>
          <div class="metric">
            <span class="metric__value">{{ formatTime(miningStore.currentRun.started_at) }}</span>
            <span class="metric__label">开始时间</span>
          </div>
        </div>
      </div>

      <!-- Error Banner -->
      <div v-if="miningStore.currentRun.error_message" class="run-detail__error-banner">
        {{ miningStore.currentRun.error_message }}
      </div>

      <!-- Progress Overview Card -->
      <div v-if="miningStore.progress" class="run-detail__progress-card">
        <div class="progress-card__row">
          <div class="progress-card__bar-wrap">
            <div class="progress-card__bar">
              <div
                class="progress-card__fill progress-card__fill--completed"
                :style="{ width: pctCompleted + '%' }"
              />
              <div
                class="progress-card__fill progress-card__fill--failed"
                :style="{ width: pctFailed + '%', left: pctCompleted + '%' }"
              />
            </div>
            <span class="progress-card__percent">{{ miningStore.progress.progress_percent }}%</span>
          </div>
        </div>
        <div class="progress-card__stats">
          <span class="progress-stat progress-stat--completed">{{ miningStore.progress.completed }} 完成</span>
          <span class="progress-stat progress-stat--failed" v-if="miningStore.progress.failed">{{ miningStore.progress.failed }} 失败</span>
          <span class="progress-stat progress-stat--skipped" v-if="miningStore.progress.skipped">{{ miningStore.progress.skipped }} 跳过</span>
          <span class="progress-stat progress-stat--processing" v-if="miningStore.progress.processing">{{ miningStore.progress.processing }} 处理中</span>
          <span class="progress-stat progress-stat--stage" v-if="miningStore.progress.current_stage">{{ stageLabel(miningStore.progress.current_stage) }}</span>
        </div>
      </div>

      <!-- Pipeline Flow -->
      <div class="run-detail__section">
        <h4 class="section-label">Pipeline 阶段</h4>
        <PipelineFlow :stage-events="miningStore.stages" />
      </div>

      <!-- Documents Table -->
      <div class="run-detail__section">
        <div class="section-header">
          <h4 class="section-label" style="margin-bottom: 0">文档处理结果 ({{ filteredDocs.length }})</h4>
          <div class="doc-filters">
            <button
              v-for="f in docFilters"
              :key="f.key"
              class="filter-tag"
              :class="{ 'filter-tag--active': activeDocFilter === f.key }"
              @click="activeDocFilter = f.key"
            >
              {{ f.label }}
              <span class="filter-tag__count" v-if="f.count">{{ f.count }}</span>
            </button>
          </div>
        </div>
        <el-table
          :data="filteredDocs"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
          @row-click="(row: Record<string, unknown>) => $router.push(`/mining/${props.runId}/documents/${row.id}`)"
          style="cursor: pointer"
        >
          <el-table-column label="文件名" min-width="200">
            <template #default="{ row }">
              <span class="doc-name">{{ docDisplayName(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusBadge :status="row.status" size="small">{{ docStatusLabel(row.status) }}</StatusBadge>
            </template>
          </el-table-column>
          <el-table-column label="阶段" width="120">
            <template #default="{ row }">
              <span class="stage-text">{{ row.current_stage ? stageLabel(row.current_stage) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <span class="action-badge" :class="`action-badge--${row.action}`">{{ actionLabel(row.action) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">
              <span class="duration-text">{{ row.duration_ms ? formatMs(row.duration_ms) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="错误" min-width="200">
            <template #default="{ row }">
              <span class="text-error" v-if="row.error_summary">{{ row.error_summary }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useDomainStore } from '@/stores/domain'
import { useMiningStore } from '@/stores/mining'
import StatusBadge from '@/components/common/StatusBadge.vue'
import PipelineFlow from '@/components/mining/PipelineFlow.vue'

const props = defineProps<{ runId: string }>()
const domainStore = useDomainStore()
const miningStore = useMiningStore()

const activeDocFilter = ref('all')
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Formatters ──

function statusLabel(status: string) {
  const map: Record<string, string> = {
    running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', pending: '等待中',
  }
  return map[status] || status
}

function docStatusLabel(status: string) {
  const map: Record<string, string> = {
    committed: '完成', processing: '处理中', failed: '失败', pending: '等待', skipped: '跳过',
  }
  return map[status] || status
}

function actionLabel(action: string) {
  const map: Record<string, string> = { new: '新增', updated: '更新', unchanged: '无变化' }
  return map[action] || action
}

function stageLabel(stage: string) {
  const map: Record<string, string> = {
    parse: '解析', segment: '分段', enrich: '增强', discourse: '语篇分析',
    retrieval_units: '检索单元构建', embedding: '向量化',
    db_write: '数据写入', commit_segments: '写入分段',
    build_relations: '写入关系', build_retrieval_units: '写入检索单元',
    select_snapshot: '快照选择', assemble_build: '构建组装', validate_build: '构建校验',
    publish_release: '发布',
  }
  return map[stage] || stage
}

function docDisplayName(row: Record<string, unknown>) {
  if (row.document_name) return row.document_name
  const dk = row.document_key as string | undefined
  if (dk?.startsWith('doc:/')) return dk.replace('doc:/', '')
  if (row.document_id) return (row.document_id as string).slice(0, 8)
  return '-'
}

function formatTime(t: string | undefined) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function formatDuration(start?: string, end?: string) {
  if (!start) return '-'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const diff = Math.round((e - s) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
}

function formatMs(ms: number) {
  if (ms < 1000) return `${ms}ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

// ── Progress card ──

const pctCompleted = computed(() => {
  const p = miningStore.progress
  if (!p || !p.total) return 0
  return Math.round((p.completed / p.total) * 100)
})

const pctFailed = computed(() => {
  const p = miningStore.progress
  if (!p || !p.total) return 0
  return Math.round((p.failed / p.total) * 100)
})

// ── Document filters ──

const docFilters = computed(() => {
  const docs = miningStore.documents
  return [
    { key: 'all', label: '全部', count: docs.length },
    { key: 'processing', label: '处理中', count: docs.filter(d => d.status === 'processing' || d.status === 'pending').length },
    { key: 'failed', label: '失败', count: docs.filter(d => d.status === 'failed').length },
    { key: 'committed', label: '已完成', count: docs.filter(d => d.status === 'committed').length },
  ]
})

const filteredDocs = computed(() => {
  if (activeDocFilter.value === 'all') return miningStore.documents
  if (activeDocFilter.value === 'processing') {
    return miningStore.documents.filter(d => d.status === 'processing' || d.status === 'pending')
  }
  return miningStore.documents.filter(d => d.status === activeDocFilter.value)
})

// ── Polling ──

async function pollOnce() {
  await Promise.all([
    miningStore.fetchProgress(props.runId),
    miningStore.fetchRunDetail(props.runId),
  ])
  if (miningStore.currentRun?.status !== 'running' && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollOnce().then(() => {
    if (miningStore.currentRun?.status === 'running') {
      pollTimer = setInterval(() => pollOnce(), 3000)
    }
  })
}

onMounted(startPolling)
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
watch(() => domainStore.currentDomain, () => {
  miningStore.clearCurrentRun()
  startPolling()
})
</script>

<style scoped>
.run-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.run-detail__back { margin-bottom: 0; }

/* Meta card */
.run-detail__meta-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 20px 22px;
  border: 1px solid var(--kb-border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.run-detail__meta-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.run-detail__id {
  font-size: 18px;
  font-weight: 700;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  color: var(--kb-text-primary);
  margin: 0;
  letter-spacing: -0.5px;
}

.run-detail__metrics {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.metric__value {
  font-size: 16px;
  font-weight: 700;
  color: var(--kb-text-primary);
  font-variant-numeric: tabular-nums;
}

.metric__value--success { color: var(--kb-success); }
.metric__value--accent { color: var(--kb-accent); }
.metric__value--danger { color: var(--kb-danger); }

.metric__label {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Error banner */
.run-detail__error-banner {
  background: var(--kb-danger-soft);
  color: var(--kb-danger);
  padding: 12px 18px;
  border-radius: var(--kb-radius-sm);
  font-size: 13px;
  border-left: 3px solid var(--kb-danger);
}

/* Progress card */
.run-detail__progress-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 16px 22px;
  border: 1px solid var(--kb-border-light);
}

.progress-card__row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-card__bar-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-card__bar {
  flex: 1;
  height: 8px;
  background: var(--kb-border-light);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.progress-card__fill {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s var(--kb-ease);
}

.progress-card__fill--completed {
  background: var(--kb-success);
  left: 0;
}

.progress-card__fill--failed {
  background: var(--kb-danger);
}

.progress-card__percent {
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--kb-text-primary);
  min-width: 48px;
  text-align: right;
}

.progress-card__stats {
  display: flex;
  gap: 16px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.progress-stat {
  font-size: 12px;
  font-weight: 500;
  color: var(--kb-text-secondary);
}

.progress-stat--completed { color: var(--kb-success); }
.progress-stat--failed { color: var(--kb-danger); }
.progress-stat--skipped { color: var(--kb-text-tertiary); }
.progress-stat--processing { color: var(--kb-accent); }
.progress-stat--stage {
  margin-left: auto;
  font-style: italic;
  color: var(--kb-text-tertiary);
}

/* Section */
.run-detail__section {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 20px 22px;
  border: 1px solid var(--kb-border-light);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0;
}

/* Doc filters */
.doc-filters {
  display: flex;
  gap: 6px;
}

.filter-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 14px;
  border: 1px solid var(--kb-border);
  background: var(--kb-bg-card);
  font-size: 11px;
  font-weight: 500;
  color: var(--kb-text-secondary);
  cursor: pointer;
  transition: all var(--kb-duration) var(--kb-ease);
}

.filter-tag:hover {
  border-color: var(--kb-accent-medium);
  color: var(--kb-accent);
}

.filter-tag--active {
  background: var(--kb-accent-soft);
  border-color: var(--kb-accent);
  color: var(--kb-accent);
}

.filter-tag__count {
  font-size: 10px;
  background: var(--kb-border-light);
  padding: 0 5px;
  border-radius: 8px;
}

.filter-tag--active .filter-tag__count {
  background: var(--kb-accent-medium);
}

/* Doc name */
.doc-name {
  font-size: 13px;
  color: var(--kb-text-primary);
}

.stage-text, .duration-text {
  font-size: 12px;
  color: var(--kb-text-secondary);
  font-variant-numeric: tabular-nums;
}

.text-muted { color: var(--kb-text-tertiary); }

/* Action badges */
.action-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.action-badge--new {
  background: var(--kb-success-soft);
  color: var(--kb-success);
}

.action-badge--updated {
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
}

.action-badge--unchanged {
  background: var(--kb-border-light);
  color: var(--kb-text-tertiary);
}

.text-error {
  font-size: 12px;
  color: var(--kb-danger);
}
</style>
