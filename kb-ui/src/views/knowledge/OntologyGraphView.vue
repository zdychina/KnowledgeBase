<!-- kb-ui/src/views/knowledge/OntologyGraphView.vue -->
<template>
  <div class="og-view">
    <div class="og-view__header">
      <div class="og-view__header-left">
        <h2 class="og-view__title">本体图谱</h2>
        <span class="og-pill og-pill--live"><span class="og-dot" />实时</span>
        <span v-if="!editMode" class="og-pill og-pill--ro">只读</span>
        <span v-else class="og-pill og-pill--edit">编辑中（草稿）</span>
        <span class="og-view__sub" v-if="active.version">
          v{{ active.version.version_no }} · {{ currentNodeCount }} 类型 · {{ graph.edges.length }} 边
        </span>
        <span class="og-view__sub" v-else>尚未引种本体</span>
      </div>
      <div class="og-view__actions">
        <el-switch v-if="!editMode" v-model="showCandidates" active-text="显示待审候选" inline-prompt />
        <el-button v-if="!editMode" @click="loadAll" :loading="loading"><el-icon><Refresh /></el-icon></el-button>
        <el-button v-if="!editMode" type="primary" @click="enterEdit">进入编辑</el-button>
        <template v-else>
          <el-button @click="exitEdit">退出编辑</el-button>
          <el-button @click="saveDraft" :loading="saving">保存草稿</el-button>
          <el-button type="primary" @click="publishDraft" :loading="publishing">发布版本</el-button>
        </template>
      </div>
    </div>

    <div class="og-body">
      <div class="og-card og-graph">
        <OntologyDiGraph
          :nodes="graph.nodes" :edges="graph.edges"
          @node-click="onNodeClick" @edge-click="onEdgeClick"
        />
      </div>

      <div class="og-card og-panel">
        <!-- 编辑工具区：仅编辑模式显示 -->
        <template v-if="editMode">
          <div class="og-edit-sec">
            <div class="og-edit-title">新建节点</div>
            <div class="og-edit-row">
              <el-input v-model="nodeForm.name" placeholder="类型名" size="small" />
              <el-select v-model="nodeForm.layer" size="small" style="width: 96px">
                <el-option label="概念层" value="concept" />
                <el-option label="实例层" value="instance" />
                <el-option label="属性层" value="property" />
              </el-select>
              <el-switch v-model="nodeForm.is_strong" active-text="强" inline-prompt size="small" />
              <el-button size="small" type="primary" @click="doAddNode">加</el-button>
            </div>
          </div>

          <div class="og-edit-sec">
            <div class="og-edit-title">新建关系类型</div>
            <div class="og-edit-row">
              <el-input v-model="relForm.name" placeholder="关系名" size="small" />
              <el-switch v-model="relForm.is_directed" active-text="有向" inline-prompt size="small" />
              <el-input v-model="relForm.inverse_name" placeholder="反向名（可选）" size="small" />
              <el-input v-model="relForm.definition" placeholder="定义（可选）" size="small" />
              <el-button size="small" type="primary" @click="doAddRelationType">加</el-button>
            </div>
          </div>

          <div class="og-edit-sec">
            <div class="og-edit-title">新建边</div>
            <div class="og-edit-row">
              <el-select v-model="edgeForm.head" size="small" placeholder="头类型" filterable>
                <el-option v-for="n in nodeNames" :key="n" :label="n" :value="n" />
              </el-select>
              <el-select v-model="edgeForm.relation" size="small" placeholder="关系" filterable>
                <el-option v-for="r in relNames" :key="r" :label="r" :value="r" />
              </el-select>
              <el-select v-model="edgeForm.tail" size="small" placeholder="尾类型" filterable>
                <el-option v-for="n in nodeNames" :key="n" :label="n" :value="n" />
              </el-select>
              <el-button size="small" type="primary" @click="doAddEdge">加</el-button>
            </div>
          </div>
        </template>

        <!-- 节点详情 -->
        <template v-if="selectedNode">
          <div class="og-panel__head">
            <span class="og-panel__name">{{ selectedNode.name }}</span>
            <span class="og-tag">{{ layerLabel(selectedNode.layer) }}</span>
            <span class="og-tag" :class="{ 'og-tag--strong': selectedNode.isStrong }">
              {{ selectedNode.isStrong ? '强' : '弱' }}
            </span>
            <span v-if="selectedNode.isCandidate" class="og-tag og-tag--cand">待审候选</span>
            <el-button v-if="editMode && !selectedNode.isCandidate" size="small" type="danger" plain @click="doRemoveNode(selectedNode.name)">删除节点</el-button>
          </div>
          <div class="og-panel__sec" v-if="selectedNode.definition">
            <div class="og-panel__label">定义</div>
            <div class="og-panel__text">{{ selectedNode.definition }}</div>
          </div>
          <div class="og-panel__sec" v-if="selectedNode.examples.length">
            <div class="og-panel__label">示例</div>
            <div class="og-chips">
              <span v-for="(ex, i) in selectedNode.examples" :key="i" class="og-chip">{{ ex }}</span>
            </div>
          </div>
          <div class="og-panel__sec" v-if="outEdges.length">
            <div class="og-panel__label">出边（作为头类型）</div>
            <div v-for="e in outEdges" :key="e.id" class="og-edge-row">
              <span class="og-rel">{{ e.relationName }}</span> → {{ e.target }}
            </div>
          </div>
          <div class="og-panel__sec" v-if="inEdges.length">
            <div class="og-panel__label">入边（作为尾类型）</div>
            <div v-for="e in inEdges" :key="e.id" class="og-edge-row">
              {{ e.source }} <span class="og-rel">{{ e.relationName }}</span> →
            </div>
          </div>
        </template>

        <!-- 边详情 -->
        <template v-else-if="selectedEdge">
          <div class="og-panel__head">
            <span class="og-panel__name">{{ selectedEdge.relationName }}</span>
            <span v-if="selectedEdge.isCandidate" class="og-tag og-tag--cand">待审候选</span>
            <el-button v-if="editMode && !selectedEdge.isCandidate" size="small" type="danger" plain @click="doRemoveEdge(selectedEdge)">删除边</el-button>
          </div>
          <div class="og-panel__sec">
            <div class="og-panel__label">连接</div>
            <div class="og-panel__text">
              {{ selectedEdge.source }} {{ selectedEdge.isDirected ? '→' : '—' }} {{ selectedEdge.target }}
            </div>
          </div>
          <div class="og-panel__sec">
            <div class="og-panel__label">方向</div>
            <div class="og-panel__text">{{ selectedEdge.isDirected ? '有向' : '无向' }}</div>
          </div>
          <div class="og-panel__sec" v-if="selectedEdge.inverseName">
            <div class="og-panel__label">反向名</div>
            <div class="og-panel__text">{{ selectedEdge.inverseName }}</div>
          </div>
          <div class="og-panel__sec" v-if="selectedEdge.definition">
            <div class="og-panel__label">定义</div>
            <div class="og-panel__text">{{ selectedEdge.definition }}</div>
          </div>
        </template>

        <div v-else-if="!editMode" class="og-panel__empty">单击节点或箭头查看定义、示例、连接约束</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { ActiveOntology, OntologyCandidate } from '@/types'
import OntologyDiGraph from '@/components/charts/OntologyDiGraph.vue'
import {
  buildOntologyGraph, parseExamples,
  type OntoGraphData, type OntoGraphNode, type OntoGraphEdge,
  type EditableOntology,
  cloneModel, addNode, removeNode, addRelationType, addEdge, removeEdge,
} from './ontologyGraph'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const saving = ref(false)
const publishing = ref(false)
const showCandidates = ref(false)
const editMode = ref(false)

const active = reactive<ActiveOntology>({ domain: '', version: null, node_types: [], relation_types: [] })
const candidates = ref<OntologyCandidate[]>([])
const graph = ref<OntoGraphData>({ nodes: [], edges: [] })

// 编辑模式下的本地草稿副本（与 active 解耦，改它不影响只读视图）
const draft = ref<EditableOntology>({ node_types: [], relation_types: [] })

const selectedNode = ref<OntoGraphNode | null>(null)
const selectedEdge = ref<OntoGraphEdge | null>(null)

const nodeForm = reactive({ name: '', layer: 'concept', is_strong: false })
const relForm = reactive({ name: '', is_directed: true, inverse_name: '', definition: '' })
const edgeForm = reactive({ head: '', relation: '', tail: '' })

// 数据指纹：只读轮询时若数据没变就不重画（避免力导布局被打断）。编辑模式不轮询。
let lastSig = ''
function dataSignature(a: ActiveOntology, cands: OntologyCandidate[]): string {
  return JSON.stringify({
    v: a.version?.version_no ?? null,
    n: a.node_types.map(t => [t.name, t.layer, t.is_strong, t.definition, t.examples_json]),
    r: a.relation_types.map(t => [t.name, t.is_directed, t.inverse_name, t.definition, t.allowed_pairs_json]),
    c: cands.map(c => [c.id, c.status, c.kind, c.proposed_name, c.layer, c.payload_json]),
  })
}

const nodeNames = computed(() => draft.value.node_types.map(t => t.name))
const relNames = computed(() => draft.value.relation_types.map(t => t.name))
const currentNodeCount = computed(() => editMode.value ? draft.value.node_types.length : active.node_types.length)

const outEdges = computed(() =>
  selectedNode.value ? graph.value.edges.filter(e => e.source === selectedNode.value!.id) : [])
const inEdges = computed(() =>
  selectedNode.value ? graph.value.edges.filter(e => e.target === selectedNode.value!.id) : [])

function rebuild() {
  // 编辑模式从草稿建图（不显示候选），只读模式从 active 建图
  if (editMode.value) {
    graph.value = buildOntologyGraph(draft.value, [], false)
  } else {
    graph.value = buildOntologyGraph(active, candidates.value, showCandidates.value)
  }
  if (selectedNode.value && !graph.value.nodes.some(n => n.id === selectedNode.value!.id)) selectedNode.value = null
  if (selectedEdge.value && !graph.value.edges.some(e => e.id === selectedEdge.value!.id)) selectedEdge.value = null
}

async function loadAll() {
  loading.value = true
  try {
    const [a, c] = await Promise.all([
      miningApi.getActiveOntology(domainStore.currentDomain),
      miningApi.getOntologyCandidates({ domain: domainStore.currentDomain, status: 'proposed' }),
    ])
    const sig = dataSignature(a, c.items)
    if (sig === lastSig) return
    lastSig = sig
    Object.assign(active, a)
    candidates.value = c.items
    if (!editMode.value) rebuild()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

// ── 编辑模式进出 ──
async function enterEdit() {
  // 先尝试拉后端已存在的草稿；没有就从当前 active 克隆一份
  try {
    const d = await miningApi.getOntologyDraft(domainStore.currentDomain)
    if (d.version) {
      draft.value = cloneModel({ node_types: d.node_types, relation_types: d.relation_types })
    } else {
      draft.value = cloneModel(active)
    }
  } catch {
    draft.value = cloneModel(active)
  }
  selectedNode.value = null
  selectedEdge.value = null
  editMode.value = true
  rebuild()
}

function exitEdit() {
  editMode.value = false
  selectedNode.value = null
  selectedEdge.value = null
  lastSig = '' // 强制下一次轮询重画回 active
  rebuild()
  loadAll()
}

function onNodeClick(id: string) {
  selectedEdge.value = null
  selectedNode.value = graph.value.nodes.find(n => n.id === id) || null
}
function onEdgeClick(id: string) {
  selectedNode.value = null
  selectedEdge.value = graph.value.edges.find(e => e.id === id) || null
}

function layerLabel(l: string) {
  return ({ concept: '概念层', instance: '实例层', property: '属性层' } as Record<string, string>)[l] || l
}

// ── 编辑操作（都作用在 draft 上，然后重画）──
function doAddNode() {
  const name = nodeForm.name.trim()
  if (!name) { ElMessage.warning('请填写类型名'); return }
  if (nodeNames.value.includes(name)) { ElMessage.warning('类型名已存在'); return }
  draft.value = addNode(draft.value, { name, layer: nodeForm.layer, isStrong: nodeForm.is_strong })
  nodeForm.name = ''
  rebuild()
}

function doAddRelationType() {
  const name = relForm.name.trim()
  if (!name) { ElMessage.warning('请填写关系名'); return }
  if (relNames.value.includes(name)) { ElMessage.warning('关系名已存在'); return }
  draft.value = addRelationType(draft.value, {
    name,
    isDirected: relForm.is_directed,
    inverseName: relForm.inverse_name.trim() || undefined,
    definition: relForm.definition.trim() || undefined,
  })
  relForm.name = ''; relForm.inverse_name = ''; relForm.definition = ''
  rebuild()
}

function doAddEdge() {
  const { head, relation, tail } = edgeForm
  if (!head || !relation || !tail) { ElMessage.warning('请选择头类型、关系、尾类型'); return }
  draft.value = addEdge(draft.value, relation, head, tail)
  edgeForm.head = ''; edgeForm.relation = ''; edgeForm.tail = ''
  rebuild()
}

async function doRemoveNode(name: string) {
  const affected = graph.value.edges.filter(e => e.source === name || e.target === name).length
  try {
    await ElMessageBox.confirm(
      `删除节点「${name}」将同时移除与它相连的 ${affected} 条边，确定吗？`,
      '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  draft.value = removeNode(draft.value, name)
  selectedNode.value = null
  rebuild()
}

function doRemoveEdge(e: OntoGraphEdge) {
  draft.value = removeEdge(draft.value, e.relationName, e.source, e.target)
  selectedEdge.value = null
  rebuild()
}

// ── 保存 / 发布 ──
function buildSavePayload() {
  return {
    node_types: draft.value.node_types.map(t => ({
      name: t.name, layer: t.layer, is_strong: t.is_strong,
      definition: t.definition ?? null,
      examples_json: parseExamples(t.examples_json),
    })),
    relation_types: draft.value.relation_types.map(t => ({
      name: t.name, layer: t.layer, is_directed: t.is_directed,
      inverse_name: t.inverse_name ?? null,
      allowed_pairs_json: Array.isArray(t.allowed_pairs_json) ? t.allowed_pairs_json : [],
      definition: t.definition ?? null,
    })),
  }
}

async function saveDraft(): Promise<boolean> {
  saving.value = true
  try {
    await miningApi.saveOntologyDraft(domainStore.currentDomain, buildSavePayload())
    ElMessage.success('草稿已保存')
    return true
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

async function publishDraft() {
  try {
    await ElMessageBox.confirm('发布后将成为当前生效本体（旧版本归档），确定吗？', '确认发布',
      { type: 'warning', confirmButtonText: '发布', cancelButtonText: '取消' })
  } catch { return }
  publishing.value = true
  try {
    const ok = await saveDraft()
    if (!ok) return
    await miningApi.publishOntologyDraft(domainStore.currentDomain)
    ElMessage.success('已发布新版本')
    editMode.value = false
    selectedNode.value = null
    selectedEdge.value = null
    lastSig = ''
    await loadAll()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '发布失败')
  } finally {
    publishing.value = false
  }
}

// ── 实时：轮询 + 重新聚焦刷新（编辑模式下都暂停）──
let timer: ReturnType<typeof setInterval> | null = null
function onFocus() { if (!editMode.value) loadAll() }
function pollTick() {
  if (editMode.value || document.visibilityState !== 'visible' || loading.value) return
  loadAll()
}

onMounted(() => {
  loadAll()
  timer = setInterval(pollTick, 5000)
  window.addEventListener('focus', onFocus)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('focus', onFocus)
})

watch(showCandidates, () => { if (!editMode.value) rebuild() })
watch(() => domainStore.currentDomain, () => {
  if (editMode.value) editMode.value = false // 切场景包时退出编辑，避免草稿串场景
  selectedNode.value = null
  selectedEdge.value = null
  lastSig = ''
  loadAll()
})
</script>

<style scoped>
.og-view { display: flex; flex-direction: column; gap: 14px; height: 100%; }
.og-view__header { display: flex; align-items: center; justify-content: space-between; }
.og-view__header-left { display: flex; align-items: center; gap: 10px; }
.og-view__title { font-size: 16px; font-weight: 650; color: var(--kb-text-primary); margin: 0; letter-spacing: -0.2px; }
.og-view__sub { font-size: 12px; color: var(--kb-text-tertiary); }
.og-view__actions { display: flex; gap: 10px; align-items: center; }
.og-pill { font-size: 11px; padding: 2px 9px; border-radius: 11px; display: inline-flex; align-items: center; gap: 5px; }
.og-pill--live { background: #ecfdf5; color: #059669; }
.og-pill--ro { background: var(--kb-border-light); color: var(--kb-text-secondary); }
.og-pill--edit { background: #fff7ed; color: #f59e0b; border: 1px solid #fed7aa; }
.og-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; }
.og-body { display: grid; grid-template-columns: 1fr 320px; gap: 14px; flex: 1; min-height: 0; }
.og-card { background: var(--kb-bg-card); border-radius: var(--kb-radius); box-shadow: var(--kb-shadow-card); border: 1px solid var(--kb-border-light); padding: 12px; }
.og-graph { min-height: 600px; }
.og-panel { display: flex; flex-direction: column; gap: 12px; overflow: auto; }
.og-edit-sec { display: flex; flex-direction: column; gap: 6px; padding-bottom: 10px; border-bottom: 1px dashed var(--kb-border-light); }
.og-edit-title { font-size: 12px; font-weight: 600; color: var(--kb-text-secondary); }
.og-edit-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.og-edit-row .el-input, .og-edit-row .el-select { flex: 1; min-width: 90px; }
.og-panel__head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.og-panel__name { font-size: 14px; font-weight: 650; color: var(--kb-text-primary); }
.og-tag { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: var(--kb-border-light); color: var(--kb-text-secondary); }
.og-tag--strong { background: var(--kb-accent-soft); color: var(--kb-accent); }
.og-tag--cand { background: #fff7ed; color: #f59e0b; border: 1px solid #fed7aa; }
.og-panel__sec { display: flex; flex-direction: column; gap: 5px; }
.og-panel__label { font-size: 11px; color: var(--kb-text-tertiary); }
.og-panel__text { font-size: 12px; color: var(--kb-text-secondary); line-height: 1.5; }
.og-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.og-chip { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: var(--kb-accent-soft); color: var(--kb-accent); }
.og-edge-row { font-size: 12px; color: var(--kb-text-secondary); padding: 2px 0; }
.og-rel { color: var(--kb-accent); }
.og-panel__empty { font-size: 12px; color: var(--kb-text-tertiary); text-align: center; padding-top: 40px; }
</style>
