<template>
  <div class="m-view">
    <div class="m-view__header">
      <div class="m-view__header-left">
        <h2 class="m-view__title">实体确认</h2>
        <span class="m-view__sub">
          {{ mentions.length }} 条待确认
          <template v-if="runId"> · run {{ runId.slice(0, 8) }}</template>
        </span>
      </div>
      <div class="m-view__actions">
        <el-button @click="load" :loading="loading"><el-icon><Refresh /></el-icon></el-button>
        <router-link v-if="runId" :to="`/mining/${runId}`">
          <el-button type="primary" plain>返回 Run 详情</el-button>
        </router-link>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="m-alert"
      title="对每条提及裁决：合并到已有对象 / 新建对象 / 丢弃（非实体）。可勾选多条批量处理。处理完可回 Run 详情点『继续挖掘』。" />

    <!-- 批量操作栏：勾选 ≥1 条时出现 -->
    <div v-if="selected.length" class="m-batchbar">
      <span class="m-batchbar__count">已选 <b>{{ selected.length }}</b> 条</span>
      <div class="m-batchbar__actions">
        <el-button type="success" size="small" plain :loading="busy" @click="batchNew">批量新建对象</el-button>
        <el-button type="primary" size="small" plain :loading="busy" @click="batchMerge">批量合并到已有</el-button>
        <el-button type="danger" size="small" plain :loading="busy" @click="batchReject">批量丢弃</el-button>
        <el-button size="small" text :disabled="busy" @click="clearSelection">取消选择</el-button>
      </div>
    </div>

    <div class="m-table-wrap">
      <el-table ref="tableRef" :data="mentions" v-loading="loading || busy" :element-loading-text="busy ? '处理中…' : undefined" row-key="id" class="kb-table" :header-cell-style="{ background: 'transparent' }" empty-text="没有待确认提及（自动放行）" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="46" reserve-selection />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="m-expand">
              <div v-if="row.segment_section" class="m-expand__section">{{ row.segment_section }}</div>
              <p class="m-expand__text">
                <template v-if="row.segment_text">
                  <template v-for="(part, i) in highlightMention(row.segment_text, row.mention_text)" :key="i">
                    <b v-if="part.hit" class="m-expand__hit">{{ part.text }}</b>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </template>
                <template v-else>（无原文，可能段落已重建）</template>
              </p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="提及文本" min-width="160">
          <template #default="{ row }"><span class="m-name">{{ row.mention_text }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="150">
          <template #default="{ row }">
            <template v-if="isUntyped(row)">
              <span class="chip chip--untyped">暂无类型</span>
              <span v-if="proposedType(row)" class="chip-hint">建议：{{ proposedType(row) }}</span>
            </template>
            <span v-else class="chip">{{ row.node_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="候选规范名" min-width="130">
          <template #default="{ row }">{{ row.canonical_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="推荐对象（点击即合并）" min-width="200">
          <template #default="{ row }">
            <div v-if="suggestions[row.id]?.length" class="m-suggests">
              <el-tag
                v-for="ent in suggestions[row.id]"
                :key="ent.id"
                size="small"
                type="primary"
                class="m-suggest-tag"
                @click="applySuggestion(row, ent)"
              >{{ ent.canonical_name }} · {{ ent.mention_count }}</el-tag>
            </div>
            <span v-else class="m-suggests__empty">—</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="80">
          <template #default="{ row }">{{ (row.confidence ?? 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button type="success" size="small" text @click="newEntity(row)">新建对象</el-button>
            <el-button type="primary" size="small" text @click="merge(row)">合并到已有</el-button>
            <el-button type="danger" size="small" text @click="reject(row)">丢弃</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 合并对话框：按名称搜索已有对象 -->
    <el-dialog v-model="mergeDialog" :title="batchMerging ? `批量合并 ${selected.length} 条到已有对象` : '合并到已有对象'" width="520px">
      <el-input v-model="searchQ" placeholder="按名称搜索对象" @input="searchEntities" clearable>
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-table :data="searchResults" class="kb-table" height="280" highlight-current-row
        @current-change="(r: GraphEntity | null) => selectedEntity = r" :header-cell-style="{ background: 'transparent' }">
        <el-table-column label="名称" prop="canonical_name" min-width="160" />
        <el-table-column label="类型" prop="node_type" width="140" />
        <el-table-column label="提及数" prop="mention_count" width="90" />
      </el-table>
      <template #footer>
        <el-button :disabled="busy" @click="mergeDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedEntity" :loading="busy" @click="confirmMerge">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { TableInstance } from 'element-plus'
import { useRoute } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { PendingMention, GraphEntity } from '@/types'

const route = useRoute()
const domainStore = useDomainStore()
const miningApi = useMiningApi()

const runId = ref<string | undefined>(route.query.run_id as string | undefined)
const loading = ref(false)
const mentions = ref<PendingMention[]>([])

const tableRef = ref<TableInstance>()
const selected = ref<PendingMention[]>([])
const suggestions = ref<Record<string, GraphEntity[]>>({})
const busy = ref(false)  // 批量/裁决等待后端时的转圈状态

const mergeDialog = ref(false)
const mergeTarget = ref<PendingMention | null>(null)
const batchMerging = ref(false)
const searchQ = ref('')
const searchResults = ref<GraphEntity[]>([])
const selectedEntity = ref<GraphEntity | null>(null)

const UNTYPED_NODE_TYPE = '__untyped__'

function onSelectionChange(rows: PendingMention[]) {
  selected.value = rows
}

// N2：本体外但被判"重要、暂无类型"的提及。实体确认里点"新建对象"即落成 __untyped__ 实体，
// 留给 N3 归纳成正式类型；这里把哨兵类型显示成"暂无类型"，并带上模型给的类型建议。
function isUntyped(row: PendingMention): boolean {
  return row.node_type === UNTYPED_NODE_TYPE
}

function proposedType(row: PendingMention): string | null {
  const pt = row.metadata_json?.proposed_type
  return typeof pt === 'string' && pt ? pt : null
}

// 把段落原文按提及文本切片，命中部分标粗（大小写不敏感、标全部出现位置）。
// 用片段数组渲染而非 v-html，避免原文里的 HTML 被注入执行。
function highlightMention(text: string, term: string): { text: string; hit: boolean }[] {
  if (!term) return [{ text, hit: false }]
  const parts: { text: string; hit: boolean }[] = []
  const lowerText = text.toLowerCase()
  const lowerTerm = term.toLowerCase()
  let cursor = 0
  while (cursor < text.length) {
    const idx = lowerText.indexOf(lowerTerm, cursor)
    if (idx === -1) { parts.push({ text: text.slice(cursor), hit: false }); break }
    if (idx > cursor) parts.push({ text: text.slice(cursor, idx), hit: false })
    parts.push({ text: text.slice(idx, idx + term.length), hit: true })
    cursor = idx + term.length
  }
  return parts
}

function clearSelection() {
  tableRef.value?.clearSelection()
}

async function load() {
  loading.value = true
  try {
    const res = await miningApi.getPendingMentions(runId.value)
    mentions.value = res.items
    prefetchSuggestions()  // §14.3：列表加载即并发预取，不阻塞渲染
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

// §14.3：为每条提及并发预取 top-3 相似已有对象（同类型、名字双向包含）
async function prefetchSuggestions() {
  suggestions.value = {}
  const dom = domainStore.currentDomain
  await Promise.all(mentions.value.map(async (m) => {
    try {
      const res = await miningApi.suggestEntities({ domain: dom, mention_text: m.mention_text, node_type: m.node_type, limit: 3 })
      if (res.items.length) suggestions.value[m.id] = res.items
    } catch { /* 推荐是辅助，失败不影响评审 */ }
  }))
}

async function applySuggestion(row: PendingMention, ent: GraphEntity) {
  busy.value = true
  try {
    await miningApi.resolveMention(row.id, { action: 'merge', entity_id: ent.id })
    ElMessage.success(`已合并到：${ent.canonical_name}`)
    await load()
  } finally {
    busy.value = false
  }
}

async function newEntity(row: PendingMention) {
  await miningApi.resolveMention(row.id, { action: 'new', domain: domainStore.currentDomain })
  ElMessage.success(`已新建对象：${row.canonical_name || row.mention_text}`)
  await load()
}

async function reject(row: PendingMention) {
  await miningApi.resolveMention(row.id, { action: 'reject' })
  ElMessage.info(`已丢弃：${row.mention_text}`)
  await load()
}

function merge(row: PendingMention) {
  batchMerging.value = false
  mergeTarget.value = row
  searchQ.value = row.canonical_name || row.mention_text
  selectedEntity.value = null
  mergeDialog.value = true
  searchEntities()
}

async function searchEntities() {
  const res = await miningApi.getGraphEntities({ domain: domainStore.currentDomain, q: searchQ.value, limit: 50 })
  searchResults.value = res.items
}

async function confirmMerge() {
  if (!selectedEntity.value) return
  busy.value = true
  try {
    if (batchMerging.value) {
      const ids = selected.value.map(m => m.id)
      const res = await miningApi.resolveMentionsBatch({ action: 'merge', mention_ids: ids, entity_id: selectedEntity.value.id })
      notifyBatch(res, `已合并到：${selectedEntity.value.canonical_name}`)
    } else {
      if (!mergeTarget.value) return
      await miningApi.resolveMention(mergeTarget.value.id, { action: 'merge', entity_id: selectedEntity.value.id })
      ElMessage.success(`已合并到：${selectedEntity.value.canonical_name}`)
    }
    mergeDialog.value = false
    await load()
  } finally {
    busy.value = false
  }
}

// ── 批量操作 ──

function notifyBatch(res: { ok: number; failed: number }, label: string) {
  if (res.failed > 0) {
    ElMessage.warning(`${label}（成功 ${res.ok} 条，失败 ${res.failed} 条）`)
  } else {
    ElMessage.success(`${label}（${res.ok} 条）`)
  }
}

async function batchReject() {
  const ids = selected.value.map(m => m.id)
  await ElMessageBox.confirm(`确认丢弃选中的 ${ids.length} 条提及？（标记为非实体）`, '批量丢弃', { type: 'warning' })
  busy.value = true
  try {
    const res = await miningApi.resolveMentionsBatch({ action: 'reject', mention_ids: ids })
    notifyBatch(res, '已丢弃')
    await load()
  } finally {
    busy.value = false
  }
}

async function batchNew() {
  const ids = selected.value.map(m => m.id)
  busy.value = true
  try {
    const res = await miningApi.resolveMentionsBatch({ action: 'new', mention_ids: ids, domain: domainStore.currentDomain })
    notifyBatch(res, '已新建对象')
    await load()
  } finally {
    busy.value = false
  }
}

function batchMerge() {
  batchMerging.value = true
  mergeTarget.value = null
  searchQ.value = selected.value[0]?.canonical_name || selected.value[0]?.mention_text || ''
  selectedEntity.value = null
  mergeDialog.value = true
  searchEntities()
}

onMounted(load)
watch(() => route.query.run_id, (v) => { runId.value = v as string | undefined; load() })
watch(() => domainStore.currentDomain, load)
</script>

<style scoped>
.m-view { display: flex; flex-direction: column; gap: 14px; }
.m-view__header { display: flex; align-items: center; justify-content: space-between; }
.m-view__header-left { display: flex; align-items: baseline; gap: 10px; }
.m-view__title { font-size: 16px; font-weight: 650; color: var(--kb-text-primary); margin: 0; letter-spacing: -0.2px; }
.m-view__sub { font-size: 12px; color: var(--kb-text-tertiary); }
.m-view__actions { display: flex; gap: 8px; }
.m-table-wrap { background: var(--kb-bg-card); border-radius: var(--kb-radius); box-shadow: var(--kb-shadow-card); border: 1px solid var(--kb-border-light); overflow: hidden; }
.m-name { font-weight: 500; color: var(--kb-text-primary); }
.chip { padding: 3px 9px; border-radius: 12px; font-size: 11px; background: var(--kb-accent-soft); color: var(--kb-accent); }
.chip--untyped { background: var(--kb-warning-soft, #fdf6ec); color: var(--kb-warning, #e6a23c); }
.chip-hint { display: inline-block; margin-left: 6px; font-size: 11px; color: var(--kb-text-secondary); }
.m-batchbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 8px 14px;
  background: var(--kb-accent-soft); border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
}
.m-batchbar__count { font-size: 13px; color: var(--kb-text-secondary); }
.m-batchbar__count b { color: var(--kb-accent); }
.m-batchbar__actions { display: flex; gap: 8px; align-items: center; }
.m-expand { padding: 6px 16px 10px 48px; }
.m-expand__section { font-size: 12px; font-weight: 600; color: var(--kb-accent); margin-bottom: 4px; }
.m-expand__text { margin: 0; font-size: 13px; line-height: 1.7; color: var(--kb-text-secondary); white-space: pre-wrap; }
.m-expand__hit { font-weight: 700; color: var(--kb-text-primary); background: var(--kb-accent-soft); border-radius: 3px; padding: 0 2px; }
.m-suggests { display: flex; flex-wrap: wrap; gap: 6px; }
.m-suggest-tag { cursor: pointer; }
.m-suggest-tag:hover { opacity: 0.8; }
.m-suggests__empty { color: var(--kb-text-tertiary); }
</style>
