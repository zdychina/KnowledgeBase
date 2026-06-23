<template>
  <div class="editor">
    <!-- toolbar -->
    <div class="editor__toolbar">
      <div class="editor__tb-left">
        <el-button text :icon="Back" @click="goBack">返回</el-button>
        <span class="editor__name">{{ paradigm?.name ?? '...' }}</span>
        <el-tag v-if="paradigm" size="small" :type="paradigm.status === 'active' ? 'success' : 'info'">
          {{ paradigm.currentVersion > 0 ? `v${paradigm.currentVersion} 已发布` : '草稿' }}
        </el-tag>
      </div>
      <div class="editor__tb-right">
        <el-button :icon="Check" :loading="saving" @click="save">保存草稿</el-button>
        <el-button :icon="Finished" :loading="validating" @click="validate">校验</el-button>
        <el-button type="primary" :icon="Promotion" :loading="publishing" @click="publish">发布</el-button>
      </div>
    </div>

    <div class="editor__body">
      <!-- palette -->
      <aside class="editor__palette">
        <OperatorPalette :operators="operators" />
      </aside>

      <!-- canvas -->
      <div class="editor__canvas" @drop="onDrop" @dragover.prevent @dragenter.prevent>
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :default-viewport="{ zoom: 0.9 }"
          :delete-key-code="'Delete'"
          fit-view-on-init
          @connect="onConnect"
          @node-click="onNodeClick"
          @pane-click="selectedNodeId = ''"
        >
          <template #node-operator="nodeProps">
            <OperatorNode :id="nodeProps.id" :data="nodeProps.data" />
          </template>
          <Background pattern-color="#cbd5e1" :gap="16" />
          <Controls />
        </VueFlow>
        <div v-if="nodes.length === 0" class="editor__canvas-hint">从左侧拖拽算子到此处开始编排</div>
      </div>

      <!-- inspector -->
      <aside class="editor__inspector">
        <!-- selected node params -->
        <section class="editor__sec">
          <div class="editor__sec-title">
            节点参数
            <el-button v-if="selectedNode" size="small" text type="danger" @click="deleteSelected">删除节点</el-button>
          </div>
          <div v-if="!selectedNode" class="editor__sec-empty">选中画布上的节点以编辑参数</div>
          <template v-else>
            <div class="editor__node-head">
              <strong>{{ selectedDef?.displayName }}</strong>
              <code>{{ selectedNode.id }}</code>
            </div>
            <p class="editor__node-desc">{{ selectedDef?.description }}</p>
            <ParamForm
              v-if="selectedDef"
              :schema-json="selectedDef.paramSchemaJson"
              :model-value="selectedNode.data.params"
              @update:model-value="updateSelectedParams"
            />
          </template>
        </section>

        <!-- output node -->
        <section class="editor__sec">
          <div class="editor__sec-title">输出（终点算子）</div>
          <el-select v-model="outputKey" size="small" style="width: 100%" placeholder="选择终点节点的输出 slot" @change="onOutputChange">
            <el-option v-for="o in outputOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </section>

        <!-- run -->
        <section class="editor__sec">
          <div class="editor__sec-title">试运行（不落库）</div>
          <el-input v-model="runQuery" size="small" placeholder="输入查询，如 aa-interface" @keyup.enter="dryRun">
            <template #append>
              <el-button :loading="running" @click="dryRun">运行</el-button>
            </template>
          </el-input>
          <RunResultPanel :result="runResult" />
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { VueFlow, useVueFlow, MarkerType, type Connection } from '@vue-flow/core'

// Loosely-typed node/edge shapes for our own state. Vue Flow's Node/Edge generics are
// extremely deep and trigger TS2589 ("excessively deep") when used in our computeds/refs;
// VueFlow applies its own types internally at the component boundary.
interface FlowNode { id: string; type: string; position: { x: number; y: number }; data: any }
interface FlowEdge { id: string; source: string; target: string; sourceHandle: string; targetHandle: string; markerEnd?: string }
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { Back, Check, Finished, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import OperatorPalette from '@/components/paradigm/OperatorPalette.vue'
import OperatorNode from '@/components/paradigm/OperatorNode.vue'
import ParamForm from '@/components/paradigm/ParamForm.vue'
import RunResultPanel from '@/components/paradigm/RunResultPanel.vue'
import { useOperatorApi } from '@/api/operator'
import type { OperatorDef, ParadigmGraph, ParadigmView, RunResult } from '@/types/operator'

const props = defineProps<{ id: string }>()
const router = useRouter()
const api = useOperatorApi()
const { screenToFlowCoordinate } = useVueFlow()

const operators = ref<OperatorDef[]>([])
const defMap = computed<Record<string, OperatorDef>>(() =>
  Object.fromEntries(operators.value.map(o => [o.type, o])))

const paradigm = ref<ParadigmView | null>(null)
const nodes = ref<FlowNode[]>([])
const edges = ref<FlowEdge[]>([])
const selectedNodeId = ref('')
const output = ref<{ nodeId: string; slot: string } | null>(null)
const outputKey = ref('')

const runQuery = ref('aa-interface')
const runResult = ref<RunResult | null>(null)

const saving = ref(false)
const validating = ref(false)
const publishing = ref(false)
const running = ref(false)

let seq = 0

const selectedNode = computed(() => nodes.value.find(n => n.id === selectedNodeId.value) || null)
const selectedDef = computed(() => selectedNode.value ? defMap.value[selectedNode.value.data.operatorType] : undefined)

const outputOptions = computed(() => {
  const opts: { label: string; value: string }[] = []
  for (const n of nodes.value) {
    const def = defMap.value[n.data.operatorType]
    for (const s of def?.outputSlots ?? []) {
      opts.push({ label: `${n.id} · ${def?.displayName} → ${s.name}`, value: `${n.id}:${s.name}` })
    }
  }
  return opts
})

// ---- load ----
onMounted(async () => {
  try {
    operators.value = await api.getCatalog()
    paradigm.value = await api.getParadigm(props.id)
    const g = paradigm.value.draftGraph
    if (g) loadGraph(g)
  } catch (e) {
    ElMessage.error('加载失败：' + errMsg(e))
  }
})

function loadGraph(g: ParadigmGraph) {
  let maxSeq = 0
  nodes.value = g.nodes.map((gn, i) => {
    const m = /(\d+)$/.exec(gn.nodeId)
    if (m) maxSeq = Math.max(maxSeq, Number(m[1]))
    return {
      id: gn.nodeId,
      type: 'operator',
      position: gn.ui ?? { x: 60 + (i % 4) * 220, y: 60 + Math.floor(i / 4) * 160 },
      data: { operatorType: gn.operatorType, def: defMap.value[gn.operatorType], params: gn.params ?? {} },
    }
  })
  edges.value = g.edges.map(ge => mkEdge(ge.fromNode, ge.fromSlot, ge.toNode, ge.toSlot))
  seq = maxSeq
  if (g.output) { output.value = g.output; outputKey.value = `${g.output.nodeId}:${g.output.slot}` }
  syncOutputFlag()
}

// ---- canvas interactions ----
function onConnect(c: Connection) {
  if (!c.source || !c.target) return
  // one incoming edge per non-variadic target slot: drop existing edge to same target slot
  const toDef = defMap.value[nodes.value.find(n => n.id === c.target)?.data.operatorType]
  const slot = toDef?.inputSlots.find(s => s.name === c.targetHandle)
  if (slot && slot.type !== 'CANDIDATE_LIST_MULTI') {
    edges.value = edges.value.filter(e => !(e.target === c.target && e.targetHandle === c.targetHandle))
  }
  edges.value.push(mkEdge(c.source, c.sourceHandle || '', c.target, c.targetHandle || ''))
}

function onDrop(e: DragEvent) {
  const type = e.dataTransfer?.getData('application/operator-type')
  if (!type) return
  const def = defMap.value[type]
  if (!def) return
  const pos = screenToFlowCoordinate({ x: e.clientX, y: e.clientY })
  const id = `${type}_${++seq}`
  nodes.value.push({
    id, type: 'operator', position: pos,
    data: { operatorType: type, def, params: defaultParams(def) },
  })
  selectedNodeId.value = id
}

function onNodeClick(e: { node: FlowNode }) { selectedNodeId.value = e.node.id }

function deleteSelected() {
  const id = selectedNodeId.value
  nodes.value = nodes.value.filter(n => n.id !== id)
  edges.value = edges.value.filter(e => e.source !== id && e.target !== id)
  if (output.value?.nodeId === id) { output.value = null; outputKey.value = '' }
  selectedNodeId.value = ''
}

function updateSelectedParams(params: Record<string, unknown>) {
  const n = selectedNode.value
  if (n) n.data.params = params
}

function onOutputChange(val: string) {
  const [nodeId, slot] = val.split(':')
  output.value = { nodeId, slot }
  syncOutputFlag()
}

function syncOutputFlag() {
  for (const n of nodes.value) n.data = { ...n.data, isOutput: n.id === output.value?.nodeId }
}

// ---- actions ----
function serialize(): ParadigmGraph {
  return {
    schemaVersion: '1.0',
    nodes: nodes.value.map(n => ({
      nodeId: n.id,
      operatorType: n.data.operatorType,
      params: n.data.params ?? {},
      ui: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    edges: edges.value.map(e => ({
      fromNode: e.source, fromSlot: e.sourceHandle || '',
      toNode: e.target, toSlot: e.targetHandle || '',
    })),
    output: output.value ?? { nodeId: '', slot: '' },
  }
}

async function save() {
  saving.value = true
  try {
    paradigm.value = await api.updateDraft(props.id, serialize())
    ElMessage.success('草稿已保存')
  } catch (e) { ElMessage.error('保存失败：' + errMsg(e)) } finally { saving.value = false }
}

async function validate() {
  validating.value = true
  try {
    const r = await api.validateInline(serialize())
    runResult.value = null
    if (r.errors && r.errors.length) {
      runResult.value = { error: 'paradigm_compile_failed', errors: r.errors }
      ElMessage.warning(`校验未通过：${r.errors.length} 个问题`)
    } else {
      ElMessage.success('校验通过 ✓')
    }
  } catch (e) {
    runResult.value = compileErrorOf(e)
    ElMessage.warning('校验未通过')
  } finally { validating.value = false }
}

async function publish() {
  try {
    await ElMessageBox.confirm('将先保存草稿、编译校验，然后发布为不可变版本。', '发布范式', { type: 'info' })
  } catch { return }
  publishing.value = true
  try {
    await api.updateDraft(props.id, serialize())
    const v = await api.publish(props.id)
    paradigm.value = await api.getParadigm(props.id)
    ElMessage.success(`已发布 v${v.version}`)
  } catch (e) {
    runResult.value = compileErrorOf(e)
    ElMessage.error('发布失败：' + errMsg(e))
  } finally { publishing.value = false }
}

async function dryRun() {
  if (!runQuery.value.trim()) { ElMessage.warning('请输入查询'); return }
  running.value = true
  runResult.value = null
  try {
    runResult.value = await api.runInline(serialize(), runQuery.value.trim(), { debug: true })
  } catch (e) {
    runResult.value = compileErrorOf(e)
    ElMessage.error('运行失败：' + errMsg(e))
  } finally { running.value = false }
}

// ---- helpers ----
function mkEdge(source: string, sourceHandle: string, target: string, targetHandle: string): FlowEdge {
  return {
    id: `e_${source}.${sourceHandle}__${target}.${targetHandle}`,
    source, target, sourceHandle, targetHandle,
    markerEnd: MarkerType.ArrowClosed,
  }
}

function defaultParams(def: OperatorDef): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  try {
    const schema = JSON.parse(def.paramSchemaJson || '{}')
    for (const [k, p] of Object.entries(schema.properties ?? {})) {
      const def_ = (p as { default?: unknown }).default
      if (def_ !== undefined) out[k] = def_
    }
  } catch { /* ignore */ }
  return out
}

function compileErrorOf(e: unknown): RunResult {
  const data = (e as { response?: { data?: RunResult } })?.response?.data
  if (data?.errors) return { error: data.error, errors: data.errors }
  return { error: errMsg(e) }
}

function errMsg(e: unknown): string {
  const a = e as { response?: { data?: { message?: string; error?: string } }; message?: string }
  return a?.response?.data?.message || a?.response?.data?.error || a?.message || '未知错误'
}

function goBack() { router.push({ name: 'paradigm' }) }
</script>

<style scoped>
.editor { display: flex; flex-direction: column; height: calc(100vh - var(--kb-header-height, 56px) - 32px); }
.editor__toolbar { display: flex; justify-content: space-between; align-items: center; padding: 0 4px 12px; }
.editor__tb-left { display: flex; align-items: center; gap: 12px; }
.editor__name { font-size: 16px; font-weight: 700; }
.editor__body { flex: 1; display: flex; gap: 12px; min-height: 0; }
.editor__palette { width: 196px; overflow-y: auto; background: var(--kb-bg-subtle, #f8fafc); border: 1px solid var(--kb-border, #e5e7eb); border-radius: 10px; padding: 10px; }
.editor__canvas { position: relative; flex: 1; border: 1px solid var(--kb-border, #e5e7eb); border-radius: 10px; overflow: hidden; background: #fbfcfe; }
.editor__canvas-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--kb-text-tertiary); pointer-events: none; font-size: 14px; }
.editor__inspector { width: 332px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
.editor__sec { background: #fff; border: 1px solid var(--kb-border, #e5e7eb); border-radius: 10px; padding: 12px 14px; }
.editor__sec-title { display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-weight: 700; color: var(--kb-text-secondary); margin-bottom: 10px; }
.editor__sec-empty { color: var(--kb-text-tertiary); font-size: 13px; }
.editor__node-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.editor__node-head code { font-size: 11px; color: #94a3b8; }
.editor__node-desc { font-size: 12px; color: var(--kb-text-tertiary); margin: 0 0 12px; line-height: 1.5; }
</style>
