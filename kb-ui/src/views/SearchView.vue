<template>
  <div class="search-view">
    <!-- Search Bar -->
    <div class="search-view__bar">
      <el-input
        v-model="query"
        placeholder="输入你的问题，例如：SMF ADD UPF 的步骤是什么"
        size="large"
        clearable
        @keyup.enter="handleSearch"
        class="search-view__input"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" size="large" @click="handleSearch" :loading="searching">
        检索
      </el-button>
    </div>

    <!-- Domain & Options -->
    <div class="search-view__options">
      <label class="search-view__option">
        <el-switch v-model="debugMode" size="small" />
        <span>Debug 模式</span>
      </label>
    </div>

    <!-- Results -->
    <template v-if="result">
      <!-- Summary -->
      <div class="search-view__summary">
        <span>找到 <strong>{{ result.items?.length ?? 0 }}</strong> 条证据</span>
        <span v-if="result.relations?.length"> · {{ result.relations.length }} 条关系</span>
        <span v-if="result.debug?.trace"> · 耗时 {{ result.debug.trace.total_duration_ms.toFixed(0) }}ms</span>
      </div>

      <!-- Understanding Card -->
      <div class="search-view__understanding" v-if="result.debug?.understanding">
        <div class="search-view__understanding-items">
          <div class="understanding-tag">
            <span class="understanding-tag__label">意图</span>
            <span class="understanding-tag__value">{{ result.debug.understanding.intent }}</span>
          </div>
          <div class="understanding-tag" v-if="result.debug.understanding.source">
            <span class="understanding-tag__label">来源</span>
            <span class="understanding-tag__value">{{ result.debug.understanding.source }}</span>
          </div>
          <div class="understanding-tag" v-if="result.debug.understanding.keywords?.length">
            <span class="understanding-tag__label">关键词</span>
            <span class="understanding-tag__value">{{ result.debug.understanding.keywords.join(', ') }}</span>
          </div>
        </div>
      </div>

      <!-- Tabs -->
      <el-tabs v-model="activeTab" class="search-view__tabs">
        <!-- Evidence Tab -->
        <el-tab-pane label="证据列表" name="evidence">
          <div class="search-view__evidence-list">
            <EvidenceCard
              v-for="(item, idx) in result.items"
              :key="item.id"
              :item="item"
              :idx="idx"
            />
          </div>
          <EmptyState v-if="!result.items?.length" text="无检索结果" />
        </el-tab-pane>

        <!-- Pipeline Tab -->
        <el-tab-pane label="Pipeline 分析" name="pipeline" v-if="result.debug?.trace">
          <div class="search-view__pipeline-section">
            <h4 class="section-label">阶段耗时</h4>
            <PipelineTrace :stages="result.debug.trace.stages" />
          </div>
          <div class="search-view__pipeline-section" v-if="result.debug.route_plan">
            <h4 class="section-label">路由计划</h4>
            <div class="pipeline-info-grid">
              <div class="pipeline-info-item">
                <span class="pipeline-info-item__label">路由数</span>
                <span class="pipeline-info-item__value">{{ result.debug.route_plan.routes_count }}</span>
              </div>
              <div class="pipeline-info-item">
                <span class="pipeline-info-item__label">融合方法</span>
                <span class="pipeline-info-item__value">{{ result.debug.route_plan.fusion_method }}</span>
              </div>
              <div class="pipeline-info-item">
                <span class="pipeline-info-item__label">重排序</span>
                <span class="pipeline-info-item__value">{{ result.debug.route_plan.rerank_method }}</span>
              </div>
              <div class="pipeline-info-item" v-if="result.debug.candidate_count">
                <span class="pipeline-info-item__label">候选数</span>
                <span class="pipeline-info-item__value">{{ result.debug.candidate_count }}</span>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- Relations Tab -->
        <el-tab-pane :label="`关系 (${result.relations?.length ?? 0})`" name="relations">
          <div class="search-view__relations-list" v-if="result.relations?.length">
            <div
              v-for="rel in result.relations"
              :key="rel.id"
              class="relation-item"
            >
              <span class="relation-item__id">{{ rel.fromId.slice(0, 6) }}</span>
              <span class="relation-item__type">{{ rel.relationType }}</span>
              <span class="relation-item__id">{{ rel.toId.slice(0, 6) }}</span>
              <span class="relation-item__dist" v-if="rel.distance != null">d={{ rel.distance }}</span>
            </div>
          </div>
          <EmptyState v-else text="无关系数据" />
        </el-tab-pane>
      </el-tabs>
    </template>

    <!-- Empty -->
    <EmptyState v-if="!result && !searching && searchedOnce" text="未找到相关结果，换个关键词试试" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { useDomainStore } from '@/stores/domain'
import { useServingApi } from '@/api/serving'
import type { SearchResult } from '@/types'
import EvidenceCard from '@/components/search/EvidenceCard.vue'
import PipelineTrace from '@/components/search/PipelineTrace.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const domainStore = useDomainStore()
const servingApi = useServingApi()

const query = ref('')
const searching = ref(false)
const searchedOnce = ref(false)
const result = ref<SearchResult | null>(null)
const activeTab = ref('evidence')
const debugMode = ref(true)

async function handleSearch() {
  if (!query.value.trim()) return
  searching.value = true
  searchedOnce.value = true
  try {
    result.value = await servingApi.search(query.value, {
      domain: domainStore.currentDomain,
      debug: debugMode.value,
    })
    activeTab.value = 'evidence'
  } catch (e) {
    console.error('Search failed:', e)
    result.value = null
  } finally {
    searching.value = false
  }
}
</script>

<style scoped>
.search-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Search bar */
.search-view__bar {
  display: flex;
  gap: 10px;
  align-items: stretch;
}

.search-view__input {
  flex: 1;
}

.search-view__input :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 16px;
}

/* Options */
.search-view__options {
  display: flex;
  gap: 16px;
  align-items: center;
}

.search-view__option {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--kb-text-secondary);
}

/* Summary */
.search-view__summary {
  font-size: 13px;
  color: var(--kb-text-secondary);
  padding: 8px 0;
}

.search-view__summary strong {
  color: var(--kb-accent);
  font-weight: 700;
}

/* Understanding */
.search-view__understanding {
  background: var(--kb-accent-soft);
  border: 1px solid var(--kb-accent-medium);
  border-radius: var(--kb-radius-sm);
  padding: 12px 16px;
}

.search-view__understanding-items {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.understanding-tag {
  display: flex;
  gap: 6px;
  align-items: center;
}

.understanding-tag__label {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-transform: uppercase;
  font-weight: 600;
}

.understanding-tag__value {
  font-size: 13px;
  color: var(--kb-text-primary);
  font-weight: 600;
}

/* Tabs */
.search-view__tabs {
  margin-top: 4px;
}

.search-view__tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

/* Evidence list */
.search-view__evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Pipeline section */
.search-view__pipeline-section {
  margin-bottom: 20px;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0 0 12px;
}

.pipeline-info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.pipeline-info-item {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius-sm);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pipeline-info-item__label {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-transform: uppercase;
  font-weight: 600;
}

.pipeline-info-item__value {
  font-size: 14px;
  font-weight: 700;
  color: var(--kb-text-primary);
}

/* Relations */
.search-view__relations-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.relation-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius-sm);
  font-size: 12px;
}

.relation-item__id {
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  color: var(--kb-accent);
  font-weight: 500;
}

.relation-item__type {
  color: var(--kb-text-primary);
  font-weight: 600;
  background: var(--kb-border-light);
  padding: 1px 8px;
  border-radius: 3px;
}

.relation-item__dist {
  color: var(--kb-text-tertiary);
  font-variant-numeric: tabular-nums;
}
</style>
