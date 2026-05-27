<template>
  <div class="runs-view">
    <!-- Header -->
    <div class="runs-view__header">
      <div class="runs-view__header-left">
        <h2 class="runs-view__title">挖掘任务</h2>
        <span class="runs-view__count">{{ miningStore.runs.length }} 个作业</span>
      </div>
      <div class="runs-view__actions">
        <el-button @click="miningStore.fetchRuns()" :loading="miningStore.loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <router-link to="/mining/create">
          <el-button type="primary">
            <el-icon class="el-icon--left"><Plus /></el-icon>
            新建 Run
          </el-button>
        </router-link>
      </div>
    </div>

    <!-- Status Filters -->
    <div class="runs-view__filters">
      <button
        v-for="f in filters"
        :key="f.key"
        class="filter-tag"
        :class="{ 'filter-tag--active': activeFilter === f.key }"
        @click="setFilter(f.key)"
      >
        {{ f.label }}
        <span class="filter-tag__count" v-if="f.count > 0">{{ f.count }}</span>
      </button>
    </div>

    <!-- Table -->
    <div class="runs-view__table-wrap">
      <el-table
        :data="filteredRuns"
        v-loading="miningStore.loading"
        class="kb-table"
        :header-cell-style="{ background: 'transparent' }"
      >
        <el-table-column label="Run ID" min-width="120">
          <template #default="{ row }">
            <router-link :to="`/mining/${row.id}`" class="table-link">{{ row.id.slice(0, 8) }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusBadge :status="row.status" size="small">{{ statusLabel(row.status) }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column label="Pipeline" min-width="160">
          <template #default="{ row }">
            <div class="doc-progress" v-if="row.total_documents > 0">
              <div class="doc-progress__bar">
                <div class="doc-progress__fill" :style="{ width: progressPercent(row) + '%' }" />
              </div>
              <span class="doc-progress__text">{{ row.committed_count || 0 }}/{{ row.total_documents }}</span>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="文档" width="160">
          <template #default="{ row }">
            <div class="doc-stats-row">
              <span class="doc-stat doc-stat--new" v-if="row.new_count" title="新增">+{{ row.new_count }}</span>
              <span class="doc-stat doc-stat--upd" v-if="row.updated_count" title="更新">~{{ row.updated_count }}</span>
              <span class="doc-stat doc-stat--skip" v-if="row.skipped_count" title="跳过">⊘{{ row.skipped_count }}</span>
              <span class="doc-stat doc-stat--fail" v-if="row.failed_count" title="失败">✕{{ row.failed_count }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.started_at, row.finished_at) }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">
            {{ formatTime(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <router-link v-if="['running','completed','failed'].includes(row.status)" :to="`/mining/${row.id}`">
              <el-button type="primary" size="small" text>详情</el-button>
            </router-link>
            <el-button v-if="row.status === 'running'" type="warning" size="small" text @click="miningStore.cancelRun(row.id)">取消</el-button>
            <el-button v-if="row.status === 'completed' && !row.build_id && row.committed_count > 0" type="success" size="small" text @click="miningStore.publishRun(row.id)">发布</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Create Dialog -->
    <el-dialog v-model="showCreateDialog" title="新建挖掘任务" width="500px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="Domain">
          <el-input :model-value="domainStore.currentDomain" disabled />
        </el-form-item>
        <el-form-item label="上传文件">
          <el-upload
            v-model:file-list="uploadFiles"
            :auto-upload="false"
            :multiple="true"
            :limit="50"
            accept=".md,.txt,.pdf,.html,.docx"
          >
            <el-button size="small">选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">支持 .md, .txt, .pdf, .html, .docx</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item label="或输入路径">
          <el-input v-model="createForm.inputPath" placeholder="手动输入目录路径（可选，优先使用上传）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import type { UploadUserFile } from 'element-plus'
import { ElMessage } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningStore } from '@/stores/mining'
import { useMiningApi } from '@/api/mining'
import StatusBadge from '@/components/common/StatusBadge.vue'

const domainStore = useDomainStore()
const miningStore = useMiningStore()
const miningApi = useMiningApi()

const showCreateDialog = ref(false)
const creating = ref(false)
const activeFilter = ref('all')
const uploadFiles = ref<UploadUserFile[]>([])
const createForm = ref({
  inputPath: '',
})

const filters = computed(() => {
  const runs = miningStore.runs
  return [
    { key: 'all', label: '全部', count: runs.length },
    { key: 'running', label: '运行中', count: runs.filter(r => r.status === 'running').length },
    { key: 'completed', label: '已完成', count: runs.filter(r => r.status === 'completed').length },
    { key: 'failed', label: '失败', count: runs.filter(r => r.status === 'failed').length },
  ]
})

const filteredRuns = computed(() => {
  if (activeFilter.value === 'all') return miningStore.runs
  return miningStore.runs.filter(r => r.status === activeFilter.value)
})

function setFilter(key: string) {
  activeFilter.value = key
}

function progressPercent(row: { committed_count: number; total_documents: number }) {
  if (!row.total_documents) return 0
  return Math.round((row.committed_count / row.total_documents) * 100)
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', pending: '等待中',
  }
  return map[status] || status
}

function formatTime(t: string) {
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

async function handleCreate() {
  creating.value = true
  try {
    let inputPath = createForm.value.inputPath

    // Upload files first if selected
    if (uploadFiles.value.length > 0) {
      const files = uploadFiles.value
        .flatMap(f => f.raw ? [f.raw as File] : [])
      if (files.length === 0) {
        ElMessage.warning('请选择有效的文件')
        creating.value = false
        return
      }
      const result = await miningApi.uploadFiles(domainStore.currentDomain, files)
      inputPath = result.storage_path
    }

    if (!inputPath) {
      ElMessage.warning('请上传文件或输入路径')
      creating.value = false
      return
    }

    await miningStore.createRun({
      domain: domainStore.currentDomain,
      input_path: inputPath,
    })
    showCreateDialog.value = false
    createForm.value.inputPath = ''
    uploadFiles.value = []
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败')
  } finally {
    creating.value = false
  }
}

onMounted(() => miningStore.fetchRuns())
watch(() => domainStore.currentDomain, () => miningStore.fetchRuns())
</script>

<style scoped>
.runs-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.runs-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.runs-view__header-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.runs-view__title {
  font-size: 16px;
  font-weight: 650;
  color: var(--kb-text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}

.runs-view__count {
  font-size: 12px;
  color: var(--kb-text-tertiary);
}

.runs-view__actions {
  display: flex;
  gap: 8px;
}

/* Filters */
.runs-view__filters {
  display: flex;
  gap: 6px;
}

.filter-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: 16px;
  border: 1px solid var(--kb-border);
  background: var(--kb-bg-card);
  font-size: 12px;
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
  font-size: 11px;
  background: var(--kb-border-light);
  padding: 0 6px;
  border-radius: 8px;
}

.filter-tag--active .filter-tag__count {
  background: var(--kb-accent-medium);
}

/* Table */
.runs-view__table-wrap {
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
  font-family: 'SF Mono', 'Cascadia Code', monospace;
}
.table-link:hover { text-decoration: underline; }

.text-muted { color: var(--kb-text-tertiary); }

/* Progress bar */
.doc-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-progress__bar {
  flex: 1;
  height: 4px;
  background: var(--kb-border-light);
  border-radius: 2px;
  overflow: hidden;
}

.doc-progress__fill {
  height: 100%;
  background: var(--kb-accent);
  border-radius: 2px;
  transition: width 0.3s var(--kb-ease);
}

.doc-progress__text {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* Doc stats */
.doc-stats-row {
  display: inline-flex;
  gap: 8px;
}

.doc-stat {
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.doc-stat--new { color: var(--kb-success); }
.doc-stat--upd { color: var(--kb-accent); }
.doc-stat--skip { color: var(--kb-text-tertiary); }
.doc-stat--fail { color: var(--kb-danger); }
</style>
