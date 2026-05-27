<template>
  <div class="doc-detail" v-loading="loading">
    <!-- Back -->
    <div class="doc-detail__back">
      <el-button text @click="$router.push('/knowledge')">
        <el-icon><ArrowLeft /></el-icon> 返回列表
      </el-button>
    </div>

    <!-- Meta -->
    <div class="doc-detail__meta" v-if="document">
      <h3 class="doc-detail__name">{{ document.document_name }}</h3>
      <div class="doc-detail__tags">
        <span class="type-badge">{{ document.document_type }}</span>
        <span class="doc-detail__date">创建于 {{ formatTime(document.created_at) }}</span>
      </div>
    </div>

    <!-- Tabs -->
    <el-tabs v-model="activeTab" v-if="document" class="doc-detail__tabs">
      <!-- Segments Tab -->
      <el-tab-pane name="segments">
        <template #label>
          段落 <span class="tab-count">{{ segments.length }}</span>
        </template>
        <el-table
          :data="segments"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
        >
          <el-table-column label="#" width="60" prop="segment_index" />
          <el-table-column label="类型" width="100" prop="block_type" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <span v-if="row.semantic_role" class="role-tag">{{ row.semantic_role }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="150">
            <template #default="{ row }">
              {{ row.section_title || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="内容预览" min-width="250">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.raw_text, 120) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="80" prop="token_count" />
        </el-table>
        <EmptyState v-if="!segments.length" text="无段落数据" />
      </el-tab-pane>

      <!-- Units Tab -->
      <el-tab-pane name="units">
        <template #label>
          检索单元 <span class="tab-count">{{ units.length }}</span>
        </template>
        <el-table
          :data="units"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
        >
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <span class="type-tag">{{ unitTypeLabel(row.unit_type) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="200" prop="title" />
          <el-table-column label="内容预览" min-width="250">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.text, 120) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="权重" width="80" prop="weight" />
        </el-table>
        <EmptyState v-if="!units.length" text="无检索单元数据" />
      </el-tab-pane>

      <!-- Relations Tab -->
      <el-tab-pane name="relations">
        <template #label>
          关系 <span class="tab-count">{{ relations.length }}</span>
        </template>
        <el-table
          :data="relations"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
        >
          <el-table-column label="源分段" min-width="160">
            <template #default="{ row }">
              <span class="text-preview">{{ relSourcePreview(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="关系类型" width="140">
            <template #default="{ row }">
              <span class="relation-type-tag">{{ relationTypeLabel(row.relation_type) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目标分段" min-width="160">
            <template #default="{ row }">
              <span class="text-preview">{{ relTargetPreview(row) }}</span>
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
        <EmptyState v-if="!relations.length" text="无关系数据" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { KnowledgeDocument, KnowledgeSegment, KnowledgeUnit, KnowledgeRelation } from '@/types'
import EmptyState from '@/components/common/EmptyState.vue'

const props = defineProps<{ docId: string }>()
const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const document = ref<KnowledgeDocument | null>(null)
const segments = ref<KnowledgeSegment[]>([])
const units = ref<KnowledgeUnit[]>([])
const relations = ref<KnowledgeRelation[]>([])
const activeTab = ref('segments')

function unitTypeLabel(type: string) {
  const map: Record<string, string> = {
    raw_text: '原始文本', contextual_text: '上下文', summary: '摘要',
    generated_question: '生成问题', entity_card: '实体卡片',
  }
  return map[type] || type
}

function relationTypeLabel(type: string) {
  const map: Record<string, string> = {
    elaboration: '详述', contrast: '对比', sequence: '顺序',
    cause_effect: '因果', problem_solution: '问题-方案',
    similarity: '相似', dependency: '依赖', reference: '引用',
  }
  return map[type] || type
}

function formatTime(t: string) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function truncate(text: string | null | undefined, len: number) {
  if (!text) return '-'
  return text.length > len ? text.slice(0, len) + '...' : text
}

function relSourcePreview(rel: KnowledgeRelation) {
  if (rel.source_text) return truncate(rel.source_text, 60)
  return rel.source_segment_id.slice(0, 8) + '...'
}

function relTargetPreview(rel: KnowledgeRelation) {
  if (rel.target_text) return truncate(rel.target_text, 60)
  return rel.target_segment_id.slice(0, 8) + '...'
}

async function loadData() {
  loading.value = true
  try {
    const [doc, segs, unts, rels] = await Promise.all([
      miningApi.getDocument(props.docId),
      miningApi.getDocumentSegments(props.docId),
      miningApi.getDocumentUnits(props.docId),
      miningApi.getDocumentRelations(props.docId),
    ])
    document.value = doc
    segments.value = segs
    units.value = unts
    relations.value = rels
  } catch {
    document.value = null
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
watch(() => domainStore.currentDomain, loadData)
</script>

<style scoped>
.doc-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.doc-detail__back { margin-bottom: 0; }

.doc-detail__meta {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 20px 22px;
  border: 1px solid var(--kb-border-light);
}

.doc-detail__name {
  font-size: 17px;
  font-weight: 650;
  color: var(--kb-text-primary);
  margin: 0 0 8px;
}

.doc-detail__tags {
  display: flex;
  align-items: center;
  gap: 10px;
}

.type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-weight: 600;
}

.doc-detail__date {
  font-size: 12px;
  color: var(--kb-text-tertiary);
}

.doc-detail__tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.tab-count {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  margin-left: 4px;
}

/* Inline tags — consistent with RunDocumentDetailView */
.role-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--kb-warning-soft);
  color: var(--kb-warning);
  font-size: 11px;
  font-weight: 600;
}

.type-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--kb-success-soft);
  color: var(--kb-success);
  font-size: 11px;
  font-weight: 600;
}

.relation-type-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-size: 11px;
  font-weight: 600;
}

.text-preview {
  font-size: 12px;
  color: var(--kb-text-secondary);
  line-height: 1.4;
}
</style>
