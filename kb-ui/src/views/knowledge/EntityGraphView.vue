<template>
  <div class="eg-view">
    <div class="eg-view__header">
      <h2 class="eg-view__title">实体图谱</h2>
      <div class="eg-view__header-right">
        <!-- 重算状态 pill -->
        <span v-if="recomputeState !== 'idle'" class="eg-recompute-pill" :class="'eg-recompute-pill--' + recomputeState">
          {{ recomputeState === 'running' ? '● 重算中' : '✓ 已同步' }}
        </span>
        <div class="eg-view__actions">
          <el-input v-model="q" placeholder="搜索对象名称" clearable style="width: 220px" @keyup.enter="loadEntities">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="nodeType" placeholder="点类型" clearable style="width: 160px" @change="loadEntities">
            <el-option v-for="t in nodeTypes" :key="t.name" :label="t.name" :value="t.name" />
          </el-select>
          <el-button @click="loadEntities" :loading="loading"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </div>
    </div>

    <div class="eg-grid">
      <!-- 左：对象列表 -->
      <div class="eg-card eg-list">
        <div class="eg-card__title">
          对象（{{ total }}）
          <span v-if="selectedRows.length > 0" class="eg-sel-hint">已选 {{ selectedRows.length }} 个</span>
        </div>
        <el-table
          ref="tableRef"
          :data="entities"
          v-loading="loading"
          class="kb-table"
          height="460"
          highlight-current-row
          @current-change="(r: GraphEntity | null) => r && selectEntity(r)"
          @selection-change="(rows: GraphEntity[]) => { selectedRows = rows }"
          :header-cell-style="{ background: 'transparent' }"
          empty-text="暂无对象，先跑挖掘落图"
        >
          <el-table-column type="selection" width="40" />
          <el-table-column label="名称" min-width="120">
            <template #default="{ row }"><span class="eg-name">{{ row.canonical_name }}</span></template>
          </el-table-column>
          <el-table-column label="类型" width="110" prop="node_type" />
          <el-table-column label="提及" width="60" prop="mention_count" />
        </el-table>

        <!-- 动作面板 -->
        <div v-if="selectedRows.length > 0" class="eg-action-panel">
          <!-- 单选：改类型 / 删除 -->
          <template v-if="selectedRows.length === 1">
            <div class="eg-action-title">
              操作：<strong>{{ selectedRows[0].canonical_name }}</strong>
              <span class="eg-cur-type" v-if="selectedRows[0].node_type">（{{ selectedRows[0].node_type }}）</span>
            </div>
            <div class="eg-action-row">
              <el-select
                v-model="newType"
                placeholder="选择新类型"
                size="small"
                style="flex:1"
              >
                <el-option label="暂无类型" value="__untyped__" />
                <el-option v-for="t in nodeTypes" :key="t.name" :label="t.name" :value="t.name" />
              </el-select>
              <el-button size="small" type="primary" :disabled="!newType" @click="handleRetype">改类型</el-button>
            </div>
            <el-button size="small" type="danger" style="width:100%;margin-top:6px" @click="handleDelete">
              删除实体
            </el-button>
          </template>

          <!-- 多选（≥2）：合并 -->
          <template v-else>
            <div class="eg-action-title">合并 {{ selectedRows.length }} 个实体</div>
            <div class="eg-action-row">
              <el-select
                v-model="mergeTargetId"
                placeholder="选择合并后主实体"
                size="small"
                style="flex:1"
              >
                <el-option
                  v-for="r in selectedRows"
                  :key="r.id"
                  :label="r.canonical_name"
                  :value="r.id"
                />
              </el-select>
              <el-button size="small" type="primary" :disabled="!mergeTargetId" @click="handleMerge">
                合并
              </el-button>
            </div>
          </template>
        </div>
      </div>

      <!-- 右：邻域图 + 出处 -->
      <div class="eg-card eg-detail">
        <div class="eg-card__title">
          {{ center ? center.canonical_name + ' 的邻域' : '选择左侧对象查看邻域' }}
          <el-radio-group v-if="center" v-model="hops" size="small" @change="loadNeighbors" style="margin-left: 12px">
            <el-radio-button :value="1">1 跳</el-radio-button>
            <el-radio-button :value="2">2 跳</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="center && graphNodes.length" class="eg-canvas">
          <ForceGraph :nodes="graphNodes" :edges="graphEdges" :categories="categories" height="420px" />
        </div>
        <EmptyState v-else-if="center && !loadingGraph" text="该对象暂无关系边" />
        <EmptyState v-else-if="!center" text="点击左侧对象，查看它在知识图谱中的邻域与出处" />

        <!-- 出处回链 -->
        <div v-if="center" class="eg-evidence">
          <div class="eg-card__title">出处回链（{{ evidence.length }}）</div>
          <div v-for="ev in evidence" :key="ev.id" class="eg-ev-item">
            <div class="eg-ev-quote">{{ ev.quote || ev.segment_text || '(无引用文本)' }}</div>
            <div class="eg-ev-meta" v-if="ev.segment_section">{{ ev.segment_section }}</div>
          </div>
          <span v-if="!evidence.length" class="text-muted">无出处记录</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { GraphEntity, GraphEvidence, OntologyNodeType, EntityNeighbors } from '@/types'
import type { GraphNode, GraphEdge } from '@/components/charts/ForceGraph.vue'
import ForceGraph from '@/components/charts/ForceGraph.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import type { ElTable } from 'element-plus'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

// ── 基础状态 ──────────────────────────────────────────────────
const loading = ref(false)
const loadingGraph = ref(false)
const entities = ref<GraphEntity[]>([])
const total = ref(0)
const q = ref('')
const nodeType = ref('')
const nodeTypes = ref<OntologyNodeType[]>([])

const center = ref<GraphEntity | null>(null)
const hops = ref(1)
const neighbors = ref<EntityNeighbors | null>(null)
const evidence = ref<GraphEvidence[]>([])

// ── mutation 相关状态 ─────────────────────────────────────────
const tableRef = ref<InstanceType<typeof ElTable> | null>(null)
const selectedRows = ref<GraphEntity[]>([])
const newType = ref('')           // 改类型面板用
const mergeTargetId = ref('')     // 合并面板用：选哪个做主实体

type RecomputeState = 'idle' | 'running' | 'synced'
const recomputeState = ref<RecomputeState>('idle')
let syncedTimer: ReturnType<typeof setTimeout> | null = null

// ── 图谱计算属性 ──────────────────────────────────────────────
const relTypes = computed(() => {
  const s = new Set((neighbors.value?.edges || []).map(e => e.relation_type))
  return Array.from(s).sort()
})
const categories = computed(() => relTypes.value.map(t => ({ name: t })))

const graphNodes = computed<GraphNode[]>(() =>
  (neighbors.value?.nodes || []).map(n => ({
    id: n.id,
    name: n.canonical_name,
    category: 0,
    value: (n.mention_count || 0) + 1,
  }))
)

const graphEdges = computed<GraphEdge[]>(() =>
  (neighbors.value?.edges || []).map(e => ({
    source: e.head_entity_id,
    target: e.tail_entity_id,
    relationType: e.relation_type,
    weight: e.confidence ?? 1,
  }))
)

// ── 数据加载 ──────────────────────────────────────────────────
async function loadEntities() {
  loading.value = true
  try {
    const res = await miningApi.getGraphEntities({
      domain: domainStore.currentDomain, q: q.value || undefined,
      type: nodeType.value || undefined, limit: 100,
    })
    entities.value = res.items
    total.value = res.total
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadNodeTypes() {
  try {
    const a = await miningApi.getActiveOntology(domainStore.currentDomain)
    nodeTypes.value = a.node_types
  } catch { /* 无本体也无妨 */ }
}

async function selectEntity(row: GraphEntity) {
  center.value = row
  await Promise.all([loadNeighbors(), loadEvidence(row.id)])
}

async function loadNeighbors() {
  if (!center.value) return
  loadingGraph.value = true
  try {
    neighbors.value = await miningApi.getEntityNeighbors(center.value.id, hops.value)
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载邻域失败')
  } finally {
    loadingGraph.value = false
  }
}

async function loadEvidence(entityId: string) {
  const res = await miningApi.getTargetEvidence(entityId)
  evidence.value = res.items
}

function reset() {
  center.value = null
  neighbors.value = null
  evidence.value = []
  selectedRows.value = []
  newType.value = ''
  mergeTargetId.value = ''
  tableRef.value?.clearSelection()
  loadEntities()
  loadNodeTypes()
}

// ── 重算状态 pill 辅助 ─────────────────────────────────────────
function setPillRunning() {
  if (syncedTimer) { clearTimeout(syncedTimer); syncedTimer = null }
  recomputeState.value = 'running'
}
function setPillSynced() {
  recomputeState.value = 'synced'
  syncedTimer = setTimeout(() => { recomputeState.value = 'idle' }, 4000)
}
function setPillIdle() {
  recomputeState.value = 'idle'
}

// ── 成功后统一刷新 ────────────────────────────────────────────
async function afterMutation(result: { recomputed_edges?: number; neighbors?: EntityNeighbors; primary_id?: string }, successMsg: string) {
  setPillSynced()
  ElMessage.success(
    result.recomputed_edges != null
      ? `${successMsg}（重算 ${result.recomputed_edges} 条关系边）`
      : successMsg
  )
  // 清选
  selectedRows.value = []
  newType.value = ''
  mergeTargetId.value = ''
  tableRef.value?.clearSelection()
  // 刷新列表
  await loadEntities()
  // 若返回了 neighbors 且当前 center 还在列表里，用返回值更新邻域图
  const primaryId = result.primary_id ?? center.value?.id
  if (result.neighbors && primaryId) {
    const stillExists = entities.value.find(e => e.id === primaryId)
    if (stillExists) {
      center.value = stillExists
      neighbors.value = result.neighbors
      await loadEvidence(primaryId)
    } else {
      center.value = null
      neighbors.value = null
      evidence.value = []
    }
  } else if (center.value) {
    // 简单地对 center 重新拉邻域（删除操作下 center 可能已不存在，这里 try-catch 无声失败）
    const stillExists = entities.value.find(e => e.id === center.value!.id)
    if (stillExists) {
      center.value = stillExists
      await loadNeighbors()
    } else {
      center.value = null
      neighbors.value = null
      evidence.value = []
    }
  }
}

// ── 合并 ──────────────────────────────────────────────────────
async function handleMerge() {
  const primaryRow = selectedRows.value.find(r => r.id === mergeTargetId.value)
  if (!primaryRow) return
  const dropIds = selectedRows.value.filter(r => r.id !== mergeTargetId.value).map(r => r.id)
  const primaryName = primaryRow.canonical_name
  const dropNames = selectedRows.value.filter(r => r.id !== mergeTargetId.value).map(r => r.canonical_name).join('、')
  const n = selectedRows.value.length

  try {
    await ElMessageBox.confirm(
      `将把 ${n} 个实体（${dropNames} → 「${primaryName}」）合并为一个实体。` +
      `被合并实体的提及将改指主实体，并重跑受影响子图的关系权重（NPMI），可能有边消失。确认合并？`,
      '合并实体',
      { confirmButtonText: '确认合并', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return // 用户取消
  }

  setPillRunning()
  try {
    const result = await miningApi.mergeEntities(mergeTargetId.value, dropIds, domainStore.currentDomain)
    await afterMutation(result, `已合并为「${primaryName}」`)
  } catch (e: unknown) {
    setPillIdle()
    ElMessage.error(e instanceof Error ? e.message : '合并失败')
  }
}

// ── 改类型 ────────────────────────────────────────────────────
async function handleRetype() {
  if (!selectedRows.value[0] || !newType.value) return
  const entity = selectedRows.value[0]
  const typeLabel = newType.value === '__untyped__' ? '暂无类型' : newType.value
  // 直接传类型名；选「暂无类型」时传 __untyped__ 哨兵（不能传空串，否则把 node_type 写成 ''，
  // 该实体会从「未定型 → 本体归纳」流程里丢失）。
  const apiType = newType.value

  try {
    await ElMessageBox.confirm(
      `将把「${entity.canonical_name}」的类型改为「${typeLabel}」。` +
      `若已存在同名同类型的实体，将自动并入它，并重算受影响的关系边。确认？`,
      '修改实体类型',
      { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  setPillRunning()
  try {
    const result = await miningApi.retypeEntity(entity.id, apiType, domainStore.currentDomain)
    await afterMutation(result, `已将「${entity.canonical_name}」改为类型「${typeLabel}」`)
  } catch (e: unknown) {
    setPillIdle()
    ElMessage.error(e instanceof Error ? e.message : '改类型失败')
  }
}

// ── 删除 ──────────────────────────────────────────────────────
async function handleDelete() {
  if (!selectedRows.value[0]) return
  const entity = selectedRows.value[0]

  try {
    await ElMessageBox.confirm(
      `将永久删除实体「${entity.canonical_name}」及其全部提及与相连边（纯减法，不影响邻居之间已有的边）。此操作不可撤销，确认删除？`,
      '删除实体',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'error' }
    )
  } catch {
    return
  }

  setPillRunning()
  try {
    await miningApi.deleteEntity(entity.id, domainStore.currentDomain)
    // deleteEntity 返回 {deleted:boolean}，没有 neighbors，统一用 afterMutation 简化路径
    await afterMutation({}, `已删除实体「${entity.canonical_name}」`)
  } catch (e: unknown) {
    setPillIdle()
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ── watch: 选中行切换时重置动作面板字段 ──────────────────────
watch(selectedRows, (rows) => {
  newType.value = ''
  if (rows.length >= 2 && !mergeTargetId.value) {
    mergeTargetId.value = rows[0].id
  }
  if (rows.length < 2) {
    mergeTargetId.value = ''
  }
})

onMounted(() => { loadEntities(); loadNodeTypes() })
watch(() => domainStore.currentDomain, reset)
</script>

<style scoped>
.eg-view { display: flex; flex-direction: column; gap: 14px; }
.eg-view__header { display: flex; align-items: center; justify-content: space-between; }
.eg-view__title { font-size: 16px; font-weight: 650; color: var(--kb-text-primary); margin: 0; letter-spacing: -0.2px; }
.eg-view__header-right { display: flex; align-items: center; gap: 12px; }
.eg-view__actions { display: flex; gap: 8px; }

/* 重算状态 pill */
.eg-recompute-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.eg-recompute-pill--running { background: #fff3e0; color: #e65100; }
.eg-recompute-pill--synced  { background: #e8f5e9; color: #2e7d32; }

.eg-grid { display: grid; grid-template-columns: 380px 1fr; gap: 14px; }
.eg-card { background: var(--kb-bg-card); border-radius: var(--kb-radius); box-shadow: var(--kb-shadow-card); border: 1px solid var(--kb-border-light); padding: 16px; }
.eg-card__title { font-size: 13px; font-weight: 600; color: var(--kb-text-secondary); margin-bottom: 12px; display: flex; align-items: center; }
.eg-sel-hint { margin-left: 8px; font-size: 11px; color: var(--kb-accent-medium, #5c7fbd); font-weight: 500; }
.eg-name { font-weight: 500; color: var(--kb-text-primary); }

/* 动作面板 */
.eg-action-panel {
  margin-top: 12px;
  padding: 12px;
  background: var(--kb-accent-soft, #f0f4fb);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
}
.eg-action-title {
  font-size: 12px;
  color: var(--kb-text-secondary);
  margin-bottom: 8px;
  line-height: 1.4;
}
.eg-cur-type { color: var(--kb-text-tertiary); }
.eg-action-row { display: flex; gap: 6px; align-items: center; }

.eg-canvas { border: 1px solid var(--kb-border-light); border-radius: var(--kb-radius); overflow: hidden; }
.eg-evidence { margin-top: 16px; }
.eg-ev-item { padding: 8px 10px; border-left: 2px solid var(--kb-accent-medium); background: var(--kb-accent-soft); border-radius: 4px; margin-bottom: 8px; }
.eg-ev-quote { font-size: 12px; color: var(--kb-text-primary); line-height: 1.5; }
.eg-ev-meta { font-size: 11px; color: var(--kb-text-tertiary); margin-top: 4px; }
.text-muted { color: var(--kb-text-tertiary); font-size: 12px; }
</style>
