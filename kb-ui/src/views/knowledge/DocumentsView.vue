<template>
  <div class="docs-view">
    <!-- Header -->
    <div class="docs-view__header">
      <div class="docs-view__header-left">
        <h2 class="docs-view__title">知识资产</h2>
        <span class="docs-view__count">{{ paginated.total }} 个文档</span>
      </div>
      <div class="docs-view__actions">
        <el-select
          v-model="selectedBatch"
          placeholder="全部 Mining 批次"
          clearable
          class="docs-view__batch-select"
        >
          <el-option
            v-for="batch in batches"
            :key="batchOptionValue(batch)"
            :label="batchLabel(batch)"
            :value="batchOptionValue(batch)"
          />
        </el-select>
        <el-button
          v-if="selectedBatchSummary?.deletable"
          type="danger"
          plain
          :loading="removingBatch"
          data-testid="remove-selected-batch"
          @click="removeBatch(selectedBatchSummary)"
        >
          下架该批次
        </el-button>
        <el-input
          v-model="searchText"
          placeholder="搜索文档..."
          size="default"
          clearable
          class="docs-view__search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button @click="loadDocuments" :loading="loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- Table -->
    <div class="docs-view__table-wrap">
      <el-table
        :data="filteredDocs"
        v-loading="loading"
        class="kb-table"
        :header-cell-style="{ background: 'transparent' }"
      >
        <el-table-column label="文档名" min-width="240">
          <template #default="{ row }">
            <router-link :to="`/knowledge/${row.id}`" class="table-link">{{ row.document_name }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="140">
          <template #default="{ row }">
            <span class="type-badge">{{ row.document_type || 'unknown' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Key" min-width="200">
          <template #default="{ row }">
            <span class="text-mono">{{ row.document_key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Mining 批次" min-width="160">
          <template #default="{ row }">
            {{ row.batch_code || (row.source_batch_id ? row.source_batch_id : '未分类批次') }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              text
              type="primary"
              :data-testid="`download-${row.id}`"
              @click="downloadDocument(row)"
            >下载</el-button>
            <el-button
              text
              type="danger"
              :loading="removingDocumentId === row.id"
              :data-testid="`remove-${row.id}`"
              @click="removeDocument(row)"
            >下架</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="docs-view__pagination" v-if="paginated.total > PAGE_SIZE">
        <el-pagination v-model:current-page="currentPage" :page-size="PAGE_SIZE" :total="paginated.total" layout="prev, pager, next" size="small" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import { apiErrorDetail } from '@/api/proxyClient'
import { filenameFromDisposition, saveBlob } from '@/utils/download'
import type { KnowledgeDocument, MiningBatchSummary } from '@/types'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const documents = ref<KnowledgeDocument[]>([])
const searchText = ref('')
const paginated = ref({ total: 0, limit: 50, offset: 0 })
const currentPage = ref(1)
const batches = ref<MiningBatchSummary[]>([])
const selectedBatch = ref('')
const batchLoading = ref(false)
const removingDocumentId = ref('')
const removingBatch = ref(false)
const PAGE_SIZE = 50
const UNCLASSIFIED_BATCH = '__unclassified__'
const WITHDRAWAL_NOTICE = '仅从当前领域的知识资产和检索结果中下架，原始文件与历史记录会保留。'

let documentRequestToken = 0
let batchRequestToken = 0
let domainGeneration = 0
let documentRemovalToken = 0
let batchRemovalToken = 0
let suppressNextPageLoad = false

const filteredDocs = computed(() => {
  if (!searchText.value) return documents.value
  const q = searchText.value.toLowerCase()
  return documents.value.filter(d =>
    d.document_name.toLowerCase().includes(q) ||
    d.document_key.toLowerCase().includes(q)
  )
})

const selectedBatchSummary = computed(() =>
  batches.value.find(batch => batchOptionValue(batch) === selectedBatch.value),
)

function batchOptionValue(batch: MiningBatchSummary) {
  return batch.unclassified || !batch.source_batch_id
    ? UNCLASSIFIED_BATCH
    : batch.source_batch_id
}

function batchLabel(batch: MiningBatchSummary) {
  const name = batch.unclassified || !batch.source_batch_id
    ? '未分类批次'
    : batch.batch_code || batch.source_batch_id
  return `${name}（${batch.active_document_count}）`
}

async function loadDocuments(): Promise<number | null> {
  const requestedDomain = domainStore.currentDomain
  const requestToken = ++documentRequestToken
  loading.value = true
  try {
    const batchParams = selectedBatch.value === UNCLASSIFIED_BATCH
      ? { unclassified: true }
      : selectedBatch.value
        ? { source_batch_id: selectedBatch.value }
        : {}
    const res = await miningApi.getDocuments({
      domain: requestedDomain,
      limit: PAGE_SIZE,
      offset: (currentPage.value - 1) * PAGE_SIZE,
      ...batchParams,
    })
    if (requestToken !== documentRequestToken || requestedDomain !== domainStore.currentDomain) {
      return null
    }
    documents.value = res.items ?? []
    paginated.value = { total: res.total, limit: res.limit, offset: res.offset }
    return res.total
  } catch (error) {
    if (requestToken === documentRequestToken && requestedDomain === domainStore.currentDomain) {
      ElMessage.error(await apiErrorDetail(error))
    }
    return null
  } finally {
    if (requestToken === documentRequestToken) loading.value = false
  }
}

async function loadBatches(): Promise<void> {
  const requestedDomain = domainStore.currentDomain
  const requestToken = ++batchRequestToken
  batchLoading.value = true
  try {
    const result = await miningApi.getBatches(requestedDomain)
    if (requestToken === batchRequestToken && requestedDomain === domainStore.currentDomain) {
      batches.value = result.items ?? []
    }
  } catch (error) {
    if (requestToken === batchRequestToken && requestedDomain === domainStore.currentDomain) {
      batches.value = []
      ElMessage.error(await apiErrorDetail(error))
    }
  } finally {
    if (requestToken === batchRequestToken) batchLoading.value = false
  }
}

async function refreshAfterRemoval(): Promise<void> {
  const [total] = await Promise.all([loadDocuments(), loadBatches()])
  if (total == null) return
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))
  if (currentPage.value > lastPage) {
    suppressNextPageLoad = true
    currentPage.value = lastPage
    await nextTick()
    await loadDocuments()
  }
}

function isConfirmCancel(error: unknown) {
  return error === 'cancel' || error === 'close'
}

function isCurrentDomainOperation(requestedDomain: string, requestedGeneration: number) {
  return requestedDomain === domainStore.currentDomain && requestedGeneration === domainGeneration
}

async function downloadDocument(row: KnowledgeDocument): Promise<void> {
  const requestedDomain = domainStore.currentDomain
  try {
    const result = await miningApi.downloadDocument(row.id, requestedDomain)
    const filename = filenameFromDisposition(result.contentDisposition, row.document_name)
    saveBlob(result.blob, filename)
  } catch (error) {
    ElMessage.error(await apiErrorDetail(error))
  }
}

async function removeDocument(row: KnowledgeDocument): Promise<void> {
  const requestedDomain = domainStore.currentDomain
  const requestedGeneration = domainGeneration
  try {
    await ElMessageBox.confirm(
      `${WITHDRAWAL_NOTICE}\n确认下架文档“${row.document_name}”吗？`,
      '确认下架文档',
      { confirmButtonText: '确认下架', cancelButtonText: '取消', type: 'warning' },
    )
  } catch (error) {
    if (!isConfirmCancel(error)) ElMessage.error(await apiErrorDetail(error))
    return
  }
  if (!isCurrentDomainOperation(requestedDomain, requestedGeneration)) return

  const removalToken = ++documentRemovalToken
  removingDocumentId.value = row.id
  try {
    await miningApi.removeDocument(row.id, requestedDomain)
    if (
      !isCurrentDomainOperation(requestedDomain, requestedGeneration) ||
      removalToken !== documentRemovalToken
    ) return
    ElMessage.success('文档已从当前领域下架')
    await refreshAfterRemoval()
  } catch (error) {
    if (
      isCurrentDomainOperation(requestedDomain, requestedGeneration) &&
      removalToken === documentRemovalToken
    ) {
      ElMessage.error(await apiErrorDetail(error))
    }
  } finally {
    if (removalToken === documentRemovalToken) removingDocumentId.value = ''
  }
}

async function removeBatch(batch: MiningBatchSummary): Promise<void> {
  if (!batch.deletable || !batch.source_batch_id) return
  const requestedDomain = domainStore.currentDomain
  const requestedGeneration = domainGeneration
  try {
    await ElMessageBox.confirm(
      `${WITHDRAWAL_NOTICE}\n该批次当前包含 ${batch.active_document_count} 个文档，确认全部下架吗？`,
      '确认下架 Mining 批次',
      { confirmButtonText: '确认下架', cancelButtonText: '取消', type: 'warning' },
    )
  } catch (error) {
    if (!isConfirmCancel(error)) ElMessage.error(await apiErrorDetail(error))
    return
  }
  if (!isCurrentDomainOperation(requestedDomain, requestedGeneration)) return

  const removalToken = ++batchRemovalToken
  removingBatch.value = true
  try {
    await miningApi.removeBatch(batch.source_batch_id, requestedDomain)
    if (
      !isCurrentDomainOperation(requestedDomain, requestedGeneration) ||
      removalToken !== batchRemovalToken
    ) return
    selectedBatch.value = ''
    currentPage.value = 1
    ElMessage.success('Mining 批次已从当前领域下架')
    await Promise.all([loadDocuments(), loadBatches()])
  } catch (error) {
    if (
      isCurrentDomainOperation(requestedDomain, requestedGeneration) &&
      removalToken === batchRemovalToken
    ) {
      ElMessage.error(await apiErrorDetail(error))
    }
  } finally {
    if (removalToken === batchRemovalToken) removingBatch.value = false
  }
}

function formatTime(t: string) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

onMounted(() => Promise.all([loadDocuments(), loadBatches()]))
watch(() => domainStore.currentDomain, () => {
  ++domainGeneration
  ++documentRemovalToken
  ++batchRemovalToken
  removingDocumentId.value = ''
  removingBatch.value = false
  selectedBatch.value = ''
  currentPage.value = 1
  documents.value = []
  batches.value = []
  void Promise.all([loadDocuments(), loadBatches()])
})
watch(currentPage, () => {
  if (suppressNextPageLoad) {
    suppressNextPageLoad = false
    return
  }
  void loadDocuments()
})
watch(selectedBatch, () => {
  if (currentPage.value !== 1) currentPage.value = 1
  else void loadDocuments()
})
</script>

<style scoped>
.docs-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.docs-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.docs-view__header-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.docs-view__title {
  font-size: 16px;
  font-weight: 650;
  color: var(--kb-text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}

.docs-view__count {
  font-size: 12px;
  color: var(--kb-text-tertiary);
}

.docs-view__actions {
  display: flex;
  gap: 8px;
}

.docs-view__search {
  width: 220px;
}

.docs-view__batch-select {
  width: 220px;
}

.docs-view__table-wrap {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  box-shadow: var(--kb-shadow-card);
  border: 1px solid var(--kb-border-light);
  overflow: hidden;
}

.docs-view__pagination {
  display: flex;
  justify-content: center;
  padding: 12px 0;
  background: var(--kb-bg-card);
  border-top: 1px solid var(--kb-border-light);
}

.table-link {
  color: var(--kb-accent);
  text-decoration: none;
  font-weight: 500;
  font-size: 13px;
}
.table-link:hover { text-decoration: underline; }

.type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-weight: 600;
}

.text-mono {
  font-size: 12px;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  color: var(--kb-text-secondary);
}
</style>
