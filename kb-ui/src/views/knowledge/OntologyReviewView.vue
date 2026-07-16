<template>
  <div class="rev-view">
    <div class="rev-view__header">
      <div class="rev-view__header-left">
        <h2 class="rev-view__title">本体确认</h2>
        <span class="rev-view__sub">
          {{ candidates.length }} 条待审 · 通过后并入新本体版本
          <template v-if="runId"> · run {{ runId.slice(0, 8) }}</template>
        </span>
      </div>
      <div class="rev-view__actions">
        <el-button @click="load" :loading="loading"><el-icon><Refresh /></el-icon></el-button>
        <el-button type="success" :disabled="!hasAccepted" @click="handlePromote" :loading="promoting">
          <el-icon class="el-icon--left"><Check /></el-icon>提交升版（并入 accepted）
        </el-button>
        <router-link v-if="runId" :to="`/mining/${runId}`">
          <el-button type="primary" plain>返回 Run 详情</el-button>
        </router-link>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="rev-alert"
      title="逐条裁决：通过（可改名）/ 拒绝。审完点右上角『提交升版』把通过的候选一次性并入一个新 active 本体版本。" />

    <div class="rev-table-wrap">
      <el-table :data="candidates" v-loading="loading" class="kb-table" :header-cell-style="{ background: 'transparent' }" empty-text="没有待审候选（自动放行）" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="rev-expand">
              <div v-if="payloadStr(row, 'definition')" class="rev-expand__line">
                <span class="rev-expand__label">描述：</span>{{ payloadStr(row, 'definition') }}
              </div>
              <div v-if="row.kind === 'node_type'" class="rev-expand__line">
                <span class="rev-expand__label">属性：</span>
                层级={{ payloadStr(row, 'layer') || '概念' }}
                <template v-if="payloadArr(row, 'examples').length">
                  · 示例：{{ payloadArr(row, 'examples').join(' / ') }}
                </template>
              </div>
              <div v-if="membersOf(row).length" class="rev-expand__members">
                <div class="rev-expand__label rev-expand__members-title">
                  成员实体（{{ membersOf(row).length }}）—— 这个类型由这些你确认过的实体归纳而来：
                </div>
                <table class="rev-member-table">
                  <thead>
                    <tr><th>成员实体</th><th class="rev-member-heat">热度</th><th>原文摘录</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(m, i) in membersOf(row)" :key="i">
                      <td>{{ m.name }}</td>
                      <td class="rev-member-heat">{{ m.document_count ?? 0 }}篇/{{ m.mention_count ?? 0 }}次</td>
                      <td class="rev-member-quote">
                        <template v-if="m.quote">「<template
                          v-for="(p, j) in quoteParts(m)" :key="j"
                        ><b v-if="p.bold" class="rev-member-mark">{{ p.text }}</b><template v-else>{{ p.text }}</template></template>」</template>
                        <template v-else>—</template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="row.kind === 'relation_type'" class="rev-expand__line text-muted">
                共现示例：{{ payloadArr(row, 'examples').join(' · ') || '无' }}
              </div>
              <div v-if="row.kind === 'node_type' && !membersOf(row).length && !payloadStr(row, 'definition')" class="text-muted">
                该候选无附加证据
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="100">
          <template #default="{ row }">
            <span class="chip" :class="row.kind === 'relation_type' ? 'chip--rel' : ''">
              {{ row.kind === 'node_type' ? '点类型' : '边类型' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <span class="chip" :class="row.source === 'escape_hatch' ? 'chip--escape' : 'chip--src'">
              {{ sourceLabel(row.source) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="提议名称" min-width="200">
          <template #default="{ row }">
            <span class="rev-name">{{ row.proposed_name }}</span>
            <span v-if="row.duplicate_of" class="chip chip--dup">⚠ 疑似重复：{{ row.duplicate_of }}</span>
            <span v-if="row.status === 'accepted'" class="tag-ok">已通过</span>
            <span v-else-if="row.status === 'rejected'" class="tag-no">已拒绝</span>
          </template>
        </el-table-column>
        <el-table-column label="热度" width="130">
          <template #default="{ row }">
            <span class="rev-heat" v-if="row.kind === 'node_type' && payloadNum(row, 'df') != null">
              <b>{{ payloadNum(row, 'df') }}</b> 篇 / <b>{{ payloadNum(row, 'support') }}</b> 次
            </span>
            <span class="text-muted" v-else-if="row.kind === 'relation_type' && payloadNum(row, 'cooccur') != null">
              共现 <b>{{ payloadNum(row, 'cooccur') }}</b> 次
            </span>
            <span class="text-muted" v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="证据 / 载荷" min-width="180">
          <template #default="{ row }">
            <span class="text-muted" v-if="row.kind === 'relation_type' && row.payload_json">
              {{ payloadStr(row, 'head_type') }} → {{ payloadStr(row, 'tail_type') }}
            </span>
            <span class="text-muted" v-else>{{ membersOf(row).length }} 个成员实体</span>
          </template>
        </el-table-column>
        <el-table-column label="打分" width="80">
          <template #default="{ row }">{{ row.score != null ? row.score.toFixed(2) : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <!-- 只有待审（proposed）候选可操作；已通过/已拒绝的不再允许重复处理 -->
            <template v-if="row.status === 'proposed'">
              <el-button type="success" size="small" text @click="accept(row)">通过</el-button>
              <el-button type="primary" size="small" text @click="rename(row)">改名通过</el-button>
              <el-button type="danger" size="small" text @click="reject(row)">拒绝</el-button>
            </template>
            <span v-else class="text-muted">已处理</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh, Check } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import type { OntologyCandidate } from '@/types'

const route = useRoute()
const domainStore = useDomainStore()
const miningApi = useMiningApi()

// 本体确认是挖掘流程的临时子页面：从 Run 详情带 run_id 进来，审完可一键返回（仿实体确认）
const runId = ref<string | undefined>(route.query.run_id as string | undefined)

const loading = ref(false)
const promoting = ref(false)
const candidates = ref<OntologyCandidate[]>([])

const hasAccepted = computed(() => candidates.value.some(c => c.status === 'accepted'))

const SOURCE_LABELS: Record<string, string> = {
  global_induction: '全局归纳',
  escape_hatch: '逃生口',
  seed: '种子',
  manual: '人工',
}
function sourceLabel(s?: string): string {
  if (!s) return '—'
  return SOURCE_LABELS[s] ?? s
}

type Payload = Record<string, unknown>
type Member = {
  entity_id?: string
  name?: string
  document_count?: number
  mention_count?: number
  quote?: string
  mention?: string   // 该实体在片段中的提及原文，用于加粗
}

function payloadOf(row: OntologyCandidate): Payload {
  return (row.payload_json ?? {}) as Payload
}
function payloadStr(row: OntologyCandidate, key: string): string {
  const v = payloadOf(row)[key]
  return v == null ? '' : String(v)
}
function payloadNum(row: OntologyCandidate, key: string): number | null {
  const v = payloadOf(row)[key]
  return typeof v === 'number' ? v : null
}
function payloadArr(row: OntologyCandidate, key: string): string[] {
  const v = payloadOf(row)[key]
  return Array.isArray(v) ? v.map(String) : []
}
function membersOf(row: OntologyCandidate): Member[] {
  const v = payloadOf(row)['members']
  return Array.isArray(v) ? (v as Member[]) : []
}
// 把原文片段按"成员实体提及"切成几段，提及那段加粗（不用 v-html，避免 XSS）
function quoteParts(m: Member): { text: string; bold: boolean }[] {
  const q = m.quote || ''
  const mention = m.mention || ''
  if (!mention) return [{ text: q, bold: false }]
  const idx = q.indexOf(mention)
  if (idx < 0) return [{ text: q, bold: false }]
  const parts: { text: string; bold: boolean }[] = []
  if (idx > 0) parts.push({ text: q.slice(0, idx), bold: false })
  parts.push({ text: mention, bold: true })
  const rest = q.slice(idx + mention.length)
  if (rest) parts.push({ text: rest, bold: false })
  return parts
}

async function load() {
  loading.value = true
  try {
    // 同时拉 proposed + accepted，方便审完一把提交
    const [p, a] = await Promise.all([
      miningApi.getOntologyCandidates({ domain: domainStore.currentDomain, status: 'proposed' }),
      miningApi.getOntologyCandidates({ domain: domainStore.currentDomain, status: 'accepted' }),
    ])
    candidates.value = [...a.items, ...p.items]
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function accept(row: OntologyCandidate) {
  await miningApi.reviewCandidate(row.id, { action: 'accept' })
  ElMessage.success(`已通过：${row.proposed_name}`)
  await load()
}

async function rename(row: OntologyCandidate) {
  try {
    const { value } = await ElMessageBox.prompt('请输入规范名称', '改名通过', {
      inputValue: row.proposed_name, confirmButtonText: '通过', cancelButtonText: '取消',
    })
    await miningApi.reviewCandidate(row.id, { action: 'accept', new_name: value })
    ElMessage.success(`已通过并改名为：${value}`)
    await load()
  } catch { /* 用户取消 */ }
}

async function reject(row: OntologyCandidate) {
  await miningApi.reviewCandidate(row.id, { action: 'reject' })
  ElMessage.info(`已拒绝：${row.proposed_name}`)
  await load()
}

async function handlePromote() {
  promoting.value = true
  try {
    const res = await miningApi.promoteCandidates(domainStore.currentDomain)
    if (res.promoted) ElMessage.success('升版成功，已激活新本体版本')
    else ElMessage.warning('没有已通过的候选，未升版')
    await load()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '升版失败')
  } finally {
    promoting.value = false
  }
}

onMounted(load)
watch(() => route.query.run_id, (v) => { runId.value = v as string | undefined })
watch(() => domainStore.currentDomain, load)
</script>

<style scoped>
.rev-view { display: flex; flex-direction: column; gap: 14px; }
.rev-view__header { display: flex; align-items: center; justify-content: space-between; }
.rev-view__header-left { display: flex; align-items: baseline; gap: 10px; }
.rev-view__title { font-size: 16px; font-weight: 650; color: var(--kb-text-primary); margin: 0; letter-spacing: -0.2px; }
.rev-view__sub { font-size: 12px; color: var(--kb-text-tertiary); }
.rev-view__actions { display: flex; gap: 8px; }
.rev-alert { }
.rev-table-wrap { background: var(--kb-bg-card); border-radius: var(--kb-radius); box-shadow: var(--kb-shadow-card); border: 1px solid var(--kb-border-light); overflow: hidden; }
.rev-name { font-weight: 500; color: var(--kb-text-primary); }
.chip { display: inline-block; padding: 3px 9px; border-radius: 12px; font-size: 11px; background: var(--kb-accent-soft); color: var(--kb-accent); }
.chip--rel { background: var(--kb-border-light); color: var(--kb-text-secondary); }
.chip--src { background: var(--kb-border-light); color: var(--kb-text-secondary); }
.chip--escape { background: rgba(230, 162, 60, 0.15); color: #b88230; font-weight: 600; }
.chip--type { background: var(--kb-accent-soft); color: var(--kb-accent); }
.chip--dup { background: rgba(245, 108, 108, 0.14); color: var(--kb-danger); font-weight: 600; margin-left: 8px; }
.tag-ok { margin-left: 8px; font-size: 11px; color: var(--kb-success); }
.tag-no { margin-left: 8px; font-size: 11px; color: var(--kb-danger); }
.text-muted { color: var(--kb-text-tertiary); font-size: 12px; }
.rev-heat { font-size: 12px; color: var(--kb-text-secondary); }
.rev-heat b { color: var(--kb-text-primary); font-weight: 650; }
.rev-expand { padding: 8px 18px 12px 48px; display: flex; flex-direction: column; gap: 8px; }
.rev-expand__label { font-size: 12px; color: var(--kb-text-tertiary); }
.rev-expand__line { font-size: 13px; color: var(--kb-text-secondary); }
.rev-expand__members { margin-top: 4px; }
.rev-expand__members-title { margin: 6px 0 4px; }
.rev-member-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.rev-member-table th { text-align: left; color: var(--kb-text-tertiary); font-weight: 500; border-bottom: 1px solid var(--kb-border-light); padding: 4px 6px; }
.rev-member-table td { padding: 4px 6px; border-bottom: 1px solid var(--kb-border-light); color: var(--kb-text-secondary); }
.rev-member-heat { width: 90px; }
.rev-member-quote { color: var(--kb-text-secondary); }
.rev-member-mark { color: var(--kb-text-primary); font-weight: 700; background: var(--kb-accent-soft); border-radius: 3px; padding: 0 2px; }
</style>
