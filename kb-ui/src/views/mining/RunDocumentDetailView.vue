<template>
  <div class="doc-detail" v-loading="miningStore.loading">
    <div class="doc-detail__back">
      <el-button text @click="$router.push(`/mining/${props.runId}`)">
        <el-icon><ArrowLeft /></el-icon> 返回 Run
      </el-button>
    </div>

    <template v-if="miningStore.currentDocument">
      <!-- Info Card -->
      <div class="doc-detail__info-card">
        <div class="doc-detail__info-left">
          <h3 class="doc-detail__name">{{ docDisplayName }}</h3>
          <StatusBadge :status="miningStore.currentDocument.status" size="small">
            {{ docStatusLabel(miningStore.currentDocument.status) }}
          </StatusBadge>
          <span class="action-badge" :class="`action-badge--${miningStore.currentDocument.action}`">
            {{ actionLabel(miningStore.currentDocument.action) }}
          </span>
        </div>
        <div class="doc-detail__info-right">
          <div class="metric" v-if="docDuration">
            <span class="metric__value">{{ docDuration }}</span>
            <span class="metric__label">耗时</span>
          </div>
          <div class="metric" v-if="miningStore.currentDocument.error_message">
            <span class="metric__value metric__value--danger">有错误</span>
          </div>
        </div>
      </div>

      <!-- Error Banner -->
      <div v-if="miningStore.currentDocument.error_message" class="doc-detail__error-banner">
        {{ miningStore.currentDocument.error_message }}
      </div>

      <!-- Stage Timeline -->
      <div class="doc-detail__section">
        <h4 class="section-label">阶段时间线</h4>
        <div class="stage-timeline">
          <div
            v-for="(stage, idx) in mergedStages"
            :key="stage.id"
            class="stage-item"
            :class="`stage-item--${stage.status}`"
          >
            <div class="stage-item__line" v-if="idx < mergedStages.length - 1" />
            <div class="stage-item__dot" />
            <div class="stage-item__content">
              <div class="stage-item__header">
                <span class="stage-item__name">{{ stageLabel(stage.stage || '') }}</span>
                <StatusBadge :status="mapStageStatus(stage.status)" size="small">
                  {{ stage.status === 'completed' ? '完成' : stage.status === 'failed' ? '失败' : stage.status === 'started' ? '进行中' : '跳过' }}
                </StatusBadge>
              </div>
              <div class="stage-item__meta">
                <span v-if="stage.duration_ms" class="stage-item__duration">{{ formatMs(stage.duration_ms) }}</span>
                <span class="stage-item__time">{{ formatTime(stage.created_at) }}</span>
              </div>
              <div v-if="stage.error_message" class="stage-item__error">{{ stage.error_message }}</div>
              <div v-if="stage.output_summary" class="stage-item__summary">{{ stage.output_summary }}</div>
            </div>
          </div>
          <div v-if="mergedStages.length === 0" class="stage-empty">暂无阶段数据</div>
        </div>
      </div>

      <!-- Artifact Summary -->
      <div class="doc-detail__section" v-if="miningStore.documentArtifacts">
        <h4 class="section-label">产物摘要</h4>
        <div class="artifact-stats">
          <div class="artifact-stat">
            <span class="artifact-stat__value">{{ miningStore.documentArtifacts.segment_count }}</span>
            <span class="artifact-stat__label">原始分段</span>
          </div>
          <div class="artifact-stat">
            <span class="artifact-stat__value">{{ miningStore.documentArtifacts.unit_count }}</span>
            <span class="artifact-stat__label">检索单元</span>
          </div>
          <div class="artifact-stat">
            <span class="artifact-stat__value">{{ miningStore.documentArtifacts.relation_count }}</span>
            <span class="artifact-stat__label">关系图谱</span>
          </div>
        </div>
      </div>

      <!-- Artifact Tabs -->
      <div class="doc-detail__section">
        <div class="section-header">
          <h4 class="section-label" style="margin-bottom: 0">知识产物</h4>
          <div class="artifact-filters">
            <button
              v-for="f in artifactTabs"
              :key="f.key"
              class="filter-tag"
              :class="{ 'filter-tag--active': activeArtifactTab === f.key }"
              @click="activeArtifactTab = f.key"
            >{{ f.label }}</button>
          </div>
        </div>

        <!-- Segments Table -->
        <el-table
          v-if="activeArtifactTab === 'segments'"
          :data="segments"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
          v-loading="artifactsLoading"
        >
          <el-table-column label="#" width="60" prop="segment_index" />
          <el-table-column label="类型" width="100" prop="block_type" />
          <el-table-column label="角色" width="100" prop="semantic_role" />
          <el-table-column label="标题" min-width="150" prop="section_title" />
          <el-table-column label="内容预览" min-width="250">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.raw_text, 120) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="80" prop="token_count" />
        </el-table>

        <!-- Units Table -->
        <el-table
          v-if="activeArtifactTab === 'units'"
          :data="units"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
          v-loading="artifactsLoading"
        >
          <el-table-column label="类型" width="120" prop="unit_type" />
          <el-table-column label="标题" min-width="200" prop="title" />
          <el-table-column label="内容预览" min-width="250">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.text, 120) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="权重" width="80" prop="weight" />
        </el-table>

        <!-- Relations Table -->
        <el-table
          v-if="activeArtifactTab === 'relations'"
          :data="relations"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
          v-loading="artifactsLoading"
        >
          <el-table-column label="源分段" min-width="120">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.source_text as string || row.source_segment_id?.slice(0, 8) || '-', 60) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="关系类型" width="140">
            <template #default="{ row }">
              <span class="relation-type-tag">{{ relationTypeLabel(row.relation_type) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目标分段" min-width="120">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.target_text as string || row.target_segment_id?.slice(0, 8) || '-', 60) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="90">
            <template #default="{ row }">
              {{ row.confidence != null ? Number(row.confidence).toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="距离" width="80">
            <template #default="{ row }">
              {{ row.distance != null ? row.distance : '-' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useMiningStore } from '@/stores/mining'
import { useMiningApi } from '@/api/mining'
import StatusBadge from '@/components/common/StatusBadge.vue'

const props = defineProps<{ runId: string; docId: string }>()
const miningStore = useMiningStore()
const miningApi = useMiningApi()

const activeArtifactTab = ref('segments')
const artifactsLoading = ref(false)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const segments = ref<any[]>([])
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const units = ref<any[]>([])
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const relations = ref<any[]>([])

const artifactTabs = [
  { key: 'segments', label: '原始分段' },
  { key: 'units', label: '检索单元' },
  { key: 'relations', label: '关系图谱' },
]

// ── Computed ──

// Merge adjacent started+completed events for the same stage into one row
const mergedStages = computed(() => {
  const raw = miningStore.documentStages
  const result: typeof raw = []
  for (let i = 0; i < raw.length; i++) {
    const cur = raw[i]
    const next = i + 1 < raw.length ? raw[i + 1] : null
    if (
      cur.status === 'started' &&
      next &&
      next.stage === cur.stage &&
      next.status === 'completed'
    ) {
      result.push({ ...next })
      i++
    } else {
      result.push(cur)
    }
  }
  return result
})

const docDisplayName = computed(() => {
  const doc = miningStore.currentDocument
  if (!doc) return '-'
  if (doc.document_name) return doc.document_name
  const dk = doc.document_key as string | undefined
  if (dk?.startsWith('doc:/')) return dk.replace('doc:/', '')
  return dk || doc.id || '-'
})

const docDuration = computed(() => {
  const doc = miningStore.currentDocument
  if (!doc || !doc.started_at) return null
  const s = new Date(doc.started_at as string).getTime()
  const e = doc.finished_at ? new Date(doc.finished_at as string).getTime() : Date.now()
  const diff = Math.round((e - s) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
})

// ── Formatters ──

function docStatusLabel(status: string) {
  const map: Record<string, string> = {
    committed: '完成', processing: '处理中', failed: '失败', pending: '等待', skipped: '跳过',
  }
  return map[status] || status
}

function actionLabel(action: string) {
  const map: Record<string, string> = { new: '新增', updated: '更新', unchanged: '无变化', NEW: '新增', UPDATE: '更新', SKIP: '跳过' }
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

function mapStageStatus(status: string): 'completed' | 'running' | 'failed' | 'cancelled' | 'pending' | 'queued' | 'succeeded' | 'dead_letter' | 'committed' | 'processing' | 'skipped' {
  const map: Record<string, string> = { started: 'running', skipped: 'skipped' }
  return (map[status] || status) as typeof mapStageStatus extends (...args: unknown[]) => infer R ? R : never
}

function formatTime(t: string | undefined) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function formatMs(ms: number) {
  if (ms < 1000) return `${ms}ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function truncate(text: string | null | undefined, len: number) {
  if (!text) return '-'
  return text.length > len ? text.slice(0, len) + '...' : text
}

function relationTypeLabel(type: string) {
  const map: Record<string, string> = {
    elaboration: '详述', contrast: '对比', sequence: '顺序',
    cause_effect: '因果', problem_solution: '问题-方案',
    similarity: '相似', dependency: '依赖', reference: '引用',
  }
  return map[type] || type
}

// ── Data loading ──

async function loadArtifacts() {
  if (activeArtifactTab.value === 'segments') {
    artifactsLoading.value = true
    try {
      const result = await miningApi.getRunDocumentSegments(props.runId, props.docId)
      segments.value = result.items
    } catch { /* ignore */ }
    finally { artifactsLoading.value = false }
  } else if (activeArtifactTab.value === 'units') {
    artifactsLoading.value = true
    try {
      const result = await miningApi.getRunDocumentUnits(props.runId, props.docId)
      units.value = result.items
    } catch { /* ignore */ }
    finally { artifactsLoading.value = false }
  } else if (activeArtifactTab.value === 'relations') {
    artifactsLoading.value = true
    try {
      const result = await miningApi.getRunDocumentRelations(props.runId, props.docId)
      relations.value = result.items
    } catch { /* ignore */ }
    finally { artifactsLoading.value = false }
  }
}

async function loadAll() {
  await miningStore.fetchDocumentDetail(props.runId, props.docId)
  loadArtifacts()
}

onMounted(loadAll)
watch(() => activeArtifactTab.value, loadArtifacts)
</script>

<style scoped>
.doc-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.doc-detail__back { margin-bottom: 0; }

/* Info card */
.doc-detail__info-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 20px 22px;
  border: 1px solid var(--kb-border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.doc-detail__info-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.doc-detail__name {
  font-size: 16px;
  font-weight: 650;
  color: var(--kb-text-primary);
  margin: 0;
}

.doc-detail__info-right {
  display: flex;
  gap: 16px;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.metric__value {
  font-size: 14px;
  font-weight: 700;
  color: var(--kb-text-primary);
  font-variant-numeric: tabular-nums;
}

.metric__value--danger { color: var(--kb-danger); }
.metric__label { font-size: 11px; color: var(--kb-text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; }

/* Error banner */
.doc-detail__error-banner {
  background: var(--kb-danger-soft);
  color: var(--kb-danger);
  padding: 12px 18px;
  border-radius: var(--kb-radius-sm);
  font-size: 13px;
  border-left: 3px solid var(--kb-danger);
}

/* Section */
.doc-detail__section {
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
  margin: 0 0 16px;
}

/* Stage timeline */
.stage-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}

.stage-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  position: relative;
  padding-bottom: 18px;
}

.stage-item__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
  background: var(--kb-border-light);
}

.stage-item--completed .stage-item__dot { background: var(--kb-success); }
.stage-item--failed .stage-item__dot { background: var(--kb-danger); }
.stage-item--started .stage-item__dot { background: var(--kb-warning); animation: pulse-dot 1.5s ease-in-out infinite; }

.stage-item__line {
  position: absolute;
  left: 4px;
  top: 14px;
  bottom: 0;
  width: 2px;
  background: var(--kb-border-light);
}

.stage-item__content {
  flex: 1;
  min-width: 0;
}

.stage-item__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.stage-item__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.stage-item__meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--kb-text-tertiary);
}

.stage-item__duration { font-variant-numeric: tabular-nums; font-weight: 600; }
.stage-item__error { font-size: 12px; color: var(--kb-danger); margin-top: 4px; }
.stage-item__summary { font-size: 12px; color: var(--kb-text-secondary); margin-top: 4px; }

.stage-empty { color: var(--kb-text-tertiary); font-size: 13px; padding: 16px 0; }

/* Artifact stats */
.artifact-stats {
  display: flex;
  gap: 24px;
}

.artifact-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.artifact-stat__value {
  font-size: 20px;
  font-weight: 700;
  color: var(--kb-text-primary);
  font-variant-numeric: tabular-nums;
}

.artifact-stat__label {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Artifact filters */
.artifact-filters { display: flex; gap: 6px; }

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

.filter-tag:hover { border-color: var(--kb-accent-medium); color: var(--kb-accent); }
.filter-tag--active { background: var(--kb-accent-soft); border-color: var(--kb-accent); color: var(--kb-accent); }

/* Common */
.text-muted { color: var(--kb-text-tertiary); font-size: 13px; }
.text-preview { font-size: 12px; color: var(--kb-text-secondary); }
.relation-type-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-size: 11px;
  font-weight: 600;
}

.action-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.action-badge--new, .action-badge--NEW { background: var(--kb-success-soft); color: var(--kb-success); }
.action-badge--updated, .action-badge--UPDATE { background: var(--kb-accent-soft); color: var(--kb-accent); }
.action-badge--unchanged, .action-badge--SKIP { background: var(--kb-border-light); color: var(--kb-text-tertiary); }

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
