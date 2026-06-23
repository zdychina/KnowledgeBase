<template>
  <div class="pd-list">
    <div class="pd-list__head">
      <div>
        <h2 class="pd-list__title">检索范式</h2>
        <p class="pd-list__sub">可插拔检索算子 DAG —— 拖拽编排、发布版本、按 id 调用</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建范式</el-button>
    </div>

    <el-table v-loading="loading" :data="paradigms" class="pd-list__table">
      <el-table-column prop="name" label="名称" min-width="160">
        <template #default="{ row }">
          <a class="pd-list__link" @click="edit(row.id)">{{ row.name }}</a>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="当前版本" width="100">
        <template #default="{ row }">{{ row.currentVersion > 0 ? `v${row.currentVersion}` : '—' }}</template>
      </el-table-column>
      <el-table-column prop="updatedAt" label="更新时间" width="180" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="edit(row.id)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState text="暂无范式，点击右上角新建" />
      </template>
    </el-table>

    <el-dialog v-model="createVisible" title="新建范式" width="460">
      <el-form label-width="72px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="唯一名称，如 emb-only-baseline" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'
import { useOperatorApi } from '@/api/operator'
import type { ParadigmView } from '@/types/operator'

const router = useRouter()
const api = useOperatorApi()

const paradigms = ref<ParadigmView[]>([])
const loading = ref(false)
const createVisible = ref(false)
const creating = ref(false)
const form = ref({ name: '', description: '' })

async function load() {
  loading.value = true
  try {
    paradigms.value = await api.listParadigms()
  } catch (e) {
    ElMessage.error('加载范式列表失败：' + errMsg(e))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', description: '' }
  createVisible.value = true
}

async function doCreate() {
  if (!form.value.name.trim()) { ElMessage.warning('请填写名称'); return }
  creating.value = true
  try {
    const pd = await api.createParadigm({ name: form.value.name.trim(), description: form.value.description })
    createVisible.value = false
    router.push({ name: 'paradigm-edit', params: { id: pd.id } })
  } catch (e) {
    ElMessage.error('创建失败：' + errMsg(e))
  } finally {
    creating.value = false
  }
}

function edit(id: string) {
  router.push({ name: 'paradigm-edit', params: { id } })
}

function statusLabel(s: string): string {
  return ({ draft: '草稿', active: '已发布', archived: '已归档' } as Record<string, string>)[s] ?? s
}

function errMsg(e: unknown): string {
  const anyE = e as { response?: { data?: { message?: string; error?: string } }; message?: string }
  return anyE?.response?.data?.message || anyE?.response?.data?.error || anyE?.message || '未知错误'
}

onMounted(load)
</script>

<style scoped>
.pd-list { padding: 4px; }
.pd-list__head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.pd-list__title { font-size: 20px; font-weight: 700; margin: 0; }
.pd-list__sub { color: var(--kb-text-tertiary); font-size: 13px; margin: 4px 0 0; }
.pd-list__link { color: var(--kb-accent, #3b82f6); cursor: pointer; font-weight: 600; }
.pd-list__table { margin-top: 4px; }
</style>
