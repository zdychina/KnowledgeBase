<template>
  <div class="docs-view">
    <!-- Header -->
    <div class="docs-view__header">
      <div class="docs-view__header-left">
        <h2 class="docs-view__title">知识资产</h2>
        <span class="docs-view__count">{{ paginated.total }} 个文档</span>
      </div>
      <div class="docs-view__actions">
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
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { KnowledgeDocument } from '@/types'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const documents = ref<KnowledgeDocument[]>([])
const searchText = ref('')
const paginated = ref({ total: 0, limit: 50, offset: 0 })

const filteredDocs = computed(() => {
  if (!searchText.value) return documents.value
  const q = searchText.value.toLowerCase()
  return documents.value.filter(d =>
    d.document_name.toLowerCase().includes(q) ||
    d.document_key.toLowerCase().includes(q)
  )
})

async function loadDocuments() {
  loading.value = true
  try {
    const res = await miningApi.getDocuments({ limit: 100 })
    documents.value = res.items ?? []
    paginated.value.total = res.total
  } catch {
    documents.value = []
  } finally {
    loading.value = false
  }
}

function formatTime(t: string) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

onMounted(loadDocuments)
watch(() => domainStore.currentDomain, loadDocuments)
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

.docs-view__table-wrap {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  box-shadow: var(--kb-shadow-card);
  border: 1px solid var(--kb-border-light);
  overflow: hidden;
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
