<template>
  <div class="graph-view">
    <!-- Header -->
    <div class="graph-view__header">
      <h2 class="graph-view__title">知识图谱</h2>
      <div class="graph-view__actions">
        <el-select v-model="filterType" placeholder="关系类型" size="default" clearable style="width: 160px">
          <el-option v-for="rt in relationTypes" :key="rt" :label="relationTypeLabel(rt)" :value="rt" />
        </el-select>
        <el-button @click="loadData" :loading="loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- Stats Bar -->
    <div class="graph-view__stats" v-if="relations.length">
      <span class="graph-view__stat">
        <strong>{{ graphNodes.length }}</strong> 节点
      </span>
      <span class="graph-view__stat">
        <strong>{{ graphEdges.length }}</strong> 条关系
      </span>
      <span class="graph-view__stat">
        <strong>{{ relationTypes.length }}</strong> 种类型
      </span>
    </div>

    <!-- Graph -->
    <div class="graph-view__canvas" v-if="graphNodes.length">
      <ForceGraph :nodes="graphNodes" :edges="graphEdges" :categories="categories" height="560px" />
    </div>

    <!-- Empty -->
    <EmptyState v-if="!loading && !graphNodes.length && loadedOnce" text="暂无关系数据，请先执行 Mining 构建" />

    <!-- Relation Table -->
    <div class="graph-view__table-section" v-if="filteredRelations.length">
      <h4 class="card-heading">关系列表</h4>
      <div class="graph-view__table-wrap">
        <el-table
          :data="pagedRelations"
          class="kb-table"
          :header-cell-style="{ background: 'transparent' }"
          size="default"
        >
          <el-table-column label="源分段" min-width="160">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.source_text, 60) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="关系" width="140">
            <template #default="{ row }">
              <span class="relation-badge">{{ relationTypeLabel(row.relation_type) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目标分段" min-width="160">
            <template #default="{ row }">
              <span class="text-preview">{{ truncate(row.target_text, 60) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="100" align="center">
            <template #default="{ row }">
              {{ row.confidence.toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column label="权重" width="80" align="center">
            <template #default="{ row }">
              {{ row.weight?.toFixed(2) ?? '-' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="graph-view__pagination" v-if="filteredRelations.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="filteredRelations.length"
          layout="prev, pager, next"
          size="small"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { KnowledgeRelation } from '@/types'
import type { GraphNode, GraphEdge } from '@/components/charts/ForceGraph.vue'
import ForceGraph from '@/components/charts/ForceGraph.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const loadedOnce = ref(false)
const relations = ref<KnowledgeRelation[]>([])
const filterType = ref('')
const currentPage = ref(1)
const pageSize = 30

const relationTypes = computed(() => {
  const types = new Set(relations.value.map(r => r.relation_type))
  return Array.from(types).sort()
})

const filteredRelations = computed(() => {
  if (!filterType.value) return relations.value
  return relations.value.filter(r => r.relation_type === filterType.value)
})

const pagedRelations = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredRelations.value.slice(start, start + pageSize)
})

const categories = computed(() =>
  relationTypes.value.map(t => ({ name: relationTypeLabel(t) }))
)

// Build graph nodes/edges from flat relation data
const graphNodes = computed<GraphNode[]>(() => {
  const nodeMap = new Map<string, GraphNode>()
  filteredRelations.value.forEach(r => {
    if (!nodeMap.has(r.source_segment_id)) {
      const catIdx = relationTypes.value.indexOf(r.relation_type)
      nodeMap.set(r.source_segment_id, {
        id: r.source_segment_id,
        name: truncate(r.source_text, 20) || r.source_segment_id.slice(0, 8),
        category: catIdx >= 0 ? catIdx : 0,
        value: 1,
      })
    } else {
      const existing = nodeMap.get(r.source_segment_id)!
      nodeMap.set(r.source_segment_id, { ...existing, value: existing.value! + 1 })
    }
    if (!nodeMap.has(r.target_segment_id)) {
      nodeMap.set(r.target_segment_id, {
        id: r.target_segment_id,
        name: truncate(r.target_text, 20) || r.target_segment_id.slice(0, 8),
        category: 0,
        value: 1,
      })
    } else {
      const existing = nodeMap.get(r.target_segment_id)!
      nodeMap.set(r.target_segment_id, { ...existing, value: existing.value! + 1 })
    }
  })
  return Array.from(nodeMap.values())
})

const graphEdges = computed<GraphEdge[]>(() =>
  filteredRelations.value.map(r => ({
    source: r.source_segment_id,
    target: r.target_segment_id,
    relationType: r.relation_type,
    weight: r.weight ?? r.confidence,
  }))
)

function truncate(text: string | null | undefined, len: number) {
  if (!text) return ''
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

async function loadData() {
  loading.value = true
  try {
    const res = await miningApi.getRelations({ limit: 500 })
    relations.value = res.items ?? []
    loadedOnce.value = true
  } catch {
    relations.value = []
    loadedOnce.value = true
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
watch(() => domainStore.currentDomain, loadData)
</script>

<style scoped>
.graph-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.graph-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.graph-view__title {
  font-size: 16px;
  font-weight: 650;
  color: var(--kb-text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}

.graph-view__actions {
  display: flex;
  gap: 8px;
}

/* Stats bar */
.graph-view__stats {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: var(--kb-text-secondary);
}

.graph-view__stat strong {
  color: var(--kb-accent);
  font-weight: 700;
}

/* Canvas */
.graph-view__canvas {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  overflow: hidden;
}

/* Table */
.graph-view__table-section {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 18px 20px;
}

.card-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0 0 14px;
}

.graph-view__table-wrap {
  overflow: hidden;
}

.graph-view__pagination {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.text-preview {
  font-size: 12px;
  color: var(--kb-text-secondary);
  line-height: 1.4;
}

.relation-badge {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 3px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-weight: 600;
}
</style>
