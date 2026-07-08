<template>
  <div class="onto-view">
    <div class="onto-view__header">
      <div class="onto-view__header-left">
        <h2 class="onto-view__title">本体版本</h2>
        <span class="onto-view__sub" v-if="active.version">
          当前 active：v{{ active.version.version_no }}
          · {{ active.node_types.length }} 类型 · {{ active.relation_types.length }} 关系
        </span>
        <span class="onto-view__sub" v-else>尚未引种本体</span>
      </div>
      <div class="onto-view__actions">
        <el-button @click="loadAll" :loading="loading"><el-icon><Refresh /></el-icon></el-button>
        <el-button type="primary" @click="showUpload = true">
          <el-icon class="el-icon--left"><Upload /></el-icon>引种本体
        </el-button>
      </div>
    </div>

    <!-- 版本列表 -->
    <div class="onto-card">
      <div class="onto-card__title">版本历史</div>
      <el-table :data="versions" v-loading="loading" class="kb-table" :header-cell-style="{ background: 'transparent' }">
        <el-table-column label="版本" width="90">
          <template #default="{ row }">v{{ row.version_no }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusBadge :status="row.status === 'active' ? 'completed' : (row.status === 'draft' ? 'pending' : 'cancelled')" size="small">
              {{ statusLabel(row.status) }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="160" prop="source" />
        <el-table-column label="备注" min-width="200" prop="note" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <!-- active 类型/关系 -->
    <template v-if="active.version">
      <!-- 节点（node）：node_name / node_description / 属性 -->
      <div class="onto-card">
        <div class="onto-card__title">节点 node（{{ active.node_types.length }}）</div>
        <div class="node-list">
          <div v-for="n in active.node_types" :key="n.id" class="node-item">
            <div class="node-item__head">
              <span class="node-item__name">{{ n.name }}</span>
              <span class="node-item__attr">{{ layerLabel(n.layer) }}</span>
              <span class="node-item__attr" :class="{ 'node-item__attr--strong': n.is_strong }">
                {{ n.is_strong ? '强' : '弱' }}
              </span>
            </div>
            <div class="node-item__desc" v-if="n.definition">{{ n.definition }}</div>
            <div class="node-item__desc node-item__desc--empty" v-else>（暂无描述）</div>
            <div class="node-item__ex" v-if="nodeExamples(n).length">
              <span class="node-item__ex-label">示例</span>
              <span v-for="(ex, i) in nodeExamples(n)" :key="i" class="node-item__ex-chip">{{ ex }}</span>
            </div>
          </div>
          <span v-if="!active.node_types.length" class="text-muted">无</span>
        </div>
      </div>
      <!-- 边类型（节点之间的关系） -->
      <div class="onto-card">
        <div class="onto-card__title">边类型（{{ active.relation_types.length }}）</div>
        <div class="chip-wrap">
          <span v-for="r in active.relation_types" :key="r.id" class="chip chip--rel">{{ r.name }}</span>
          <span v-if="!active.relation_types.length" class="text-muted">无</span>
        </div>
      </div>
    </template>

    <!-- 引种弹窗 -->
    <el-dialog v-model="showUpload" title="引种本体（上传 YAML）" width="560px">
      <el-alert type="info" :closable="false" show-icon class="onto-alert"
        title="上传一份本体定义文件（YAML），冷启动建立 v1。已有 active 版本则跳过。" />
      <el-upload :auto-upload="false" :show-file-list="true" :limit="1" accept=".yaml,.yml"
        v-model:file-list="uploadFiles" :on-change="onFilePicked">
        <el-button size="small">选择 YAML 文件</el-button>
        <template #tip><div class="el-upload__tip">支持 .yaml / .yml，包含 node_types / relation_types / aliases</div></template>
      </el-upload>
      <el-input v-if="yamlText" v-model="yamlText" type="textarea" :rows="10" class="onto-yaml" />
      <template #footer>
        <el-button @click="showUpload = false">取消</el-button>
        <el-button type="primary" @click="handleBootstrap" :loading="bootstrapping" :disabled="!yamlText">引种</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadUserFile } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { OntologyVersion, ActiveOntology, OntologyNodeType } from '@/types'
import StatusBadge from '@/components/common/StatusBadge.vue'

const domainStore = useDomainStore()
const miningApi = useMiningApi()

const loading = ref(false)
const versions = ref<OntologyVersion[]>([])
const active = reactive<ActiveOntology>({ domain: '', version: null, node_types: [], relation_types: [] })

const showUpload = ref(false)
const bootstrapping = ref(false)
const uploadFiles = ref<UploadUserFile[]>([])
const yamlText = ref('')

async function loadAll() {
  loading.value = true
  try {
    const [v, a] = await Promise.all([
      miningApi.getOntologyVersions(domainStore.currentDomain),
      miningApi.getActiveOntology(domainStore.currentDomain),
    ])
    versions.value = v.items
    Object.assign(active, a)
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onFilePicked(file: UploadUserFile) {
  const raw = file.raw as File | undefined
  if (raw) yamlText.value = await raw.text()
}

async function handleBootstrap() {
  bootstrapping.value = true
  try {
    const res = await miningApi.bootstrapOntology(yamlText.value, domainStore.currentDomain)
    if (res.skipped) ElMessage.warning(`已有 active 版本（v${res.version_no}），跳过引种`)
    else ElMessage.success(`引种成功：v${res.version_no}，${res.node_types} 类型 / ${res.relation_types} 关系 / ${res.aliases} 别名`)
    showUpload.value = false
    yamlText.value = ''
    uploadFiles.value = []
    await loadAll()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '引种失败')
  } finally {
    bootstrapping.value = false
  }
}

function statusLabel(s: string) {
  return ({ active: '使用中', draft: '草稿', superseded: '已替代' } as Record<string, string>)[s] || s
}
function layerLabel(l?: string) {
  return ({ concept: '概念层', instance: '实例层', property: '属性层' } as Record<string, string>)[l || ''] || (l || '概念层')
}
function nodeExamples(n: OntologyNodeType): string[] {
  let ex: unknown = n.examples_json
  if (typeof ex === 'string') { try { ex = JSON.parse(ex) } catch { ex = [] } }
  return Array.isArray(ex) ? ex.map(String).slice(0, 6) : []
}
function formatTime(t?: string) { return t ? new Date(t).toLocaleString('zh-CN') : '-' }

onMounted(loadAll)
watch(() => domainStore.currentDomain, loadAll)
</script>

<style scoped>
.onto-view { display: flex; flex-direction: column; gap: 14px; }
.onto-view__header { display: flex; align-items: center; justify-content: space-between; }
.onto-view__header-left { display: flex; align-items: baseline; gap: 10px; }
.onto-view__title { font-size: 16px; font-weight: 650; color: var(--kb-text-primary); margin: 0; letter-spacing: -0.2px; }
.onto-view__sub { font-size: 12px; color: var(--kb-text-tertiary); }
.onto-view__actions { display: flex; gap: 8px; }
.onto-card { background: var(--kb-bg-card); border-radius: var(--kb-radius); box-shadow: var(--kb-shadow-card); border: 1px solid var(--kb-border-light); padding: 16px; }
.onto-card__title { font-size: 13px; font-weight: 600; color: var(--kb-text-secondary); margin-bottom: 12px; }
.chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.node-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.node-item { border: 1px solid var(--kb-border-light); border-radius: var(--kb-radius); padding: 10px 12px; background: var(--kb-bg-card); display: flex; flex-direction: column; gap: 6px; }
.node-item__head { display: flex; align-items: center; gap: 8px; }
.node-item__name { font-size: 13px; font-weight: 650; color: var(--kb-text-primary); }
.node-item__attr { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: var(--kb-border-light); color: var(--kb-text-secondary); }
.node-item__attr--strong { background: var(--kb-accent-soft); color: var(--kb-accent); border: 1px solid var(--kb-accent-medium); }
.node-item__desc { font-size: 12px; color: var(--kb-text-secondary); line-height: 1.5; }
.node-item__desc--empty { color: var(--kb-text-tertiary); font-style: italic; }
.node-item__ex { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.node-item__ex-label { font-size: 11px; color: var(--kb-text-tertiary); }
.node-item__ex-chip { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: var(--kb-accent-soft); color: var(--kb-accent); }
.chip { padding: 4px 10px; border-radius: 14px; font-size: 12px; background: var(--kb-accent-soft); color: var(--kb-accent); border: 1px solid var(--kb-accent-medium); }
.chip--strong { font-weight: 600; }
.chip--rel { background: var(--kb-border-light); color: var(--kb-text-secondary); border-color: var(--kb-border); }
.text-muted { color: var(--kb-text-tertiary); font-size: 12px; }
.onto-alert { margin-bottom: 12px; }
.onto-yaml { margin-top: 12px; font-family: 'SF Mono', monospace; }
</style>
