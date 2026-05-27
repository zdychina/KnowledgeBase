<template>
  <section class="settings-card">
    <div class="card-heading-row">
      <h3 class="card-heading">Runtime Overrides</h3>
      <el-button text type="primary" @click="handleAddOverride">+ 新增</el-button>
    </div>

    <div v-if="!overrideDraft.length" class="empty-state">
      当前 Domain 还没有 override
    </div>

    <div v-else class="override-list">
      <div v-for="item in overrideDraft" :key="item.override_id" class="override-item">
        <div class="override-item__head">
          <el-select v-model="item.service_name" class="override-item__svc">
            <el-option label="mining" value="mining" />
            <el-option label="serving" value="serving" />
            <el-option label="llm" value="llm" />
            <el-option label="ui" value="ui" />
          </el-select>
          <el-input v-model="item.config_scope" placeholder="scope" />
          <el-input v-model="item.version_tag" placeholder="version" />
          <el-button text type="danger" size="small" @click="handleRemoveOverride(item.override_id)">删除</el-button>
        </div>
        <div class="override-item__editor">
          <el-input v-model="item.jsonText" type="textarea" :rows="5" />
          <el-button text size="small" @click="formatJson(item)">格式化 JSON</el-button>
        </div>
      </div>
    </div>

    <div v-if="jsonError" class="error-banner">{{ jsonError }}</div>

    <div class="card-footer">
      <el-button type="primary" @click="handleSaveOverrides">保存 Overrides</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ControlPlaneDomainDetail, ControlPlaneRuntimeOverride } from '@/types'

type OverrideDraft = ControlPlaneRuntimeOverride & { jsonText: string }

const props = defineProps<{
  domain: ControlPlaneDomainDetail
}>()

const emit = defineEmits<{
  saveOverrides: [overrides: ControlPlaneRuntimeOverride[]]
}>()

const overrideDraft = ref<OverrideDraft[]>([])
const jsonError = ref('')

watch(() => props.domain, (val) => {
  if (!val) {
    overrideDraft.value = []
    return
  }
  overrideDraft.value = val.overrides.map(item => ({
    ...item,
    jsonText: JSON.stringify(item.config_json, null, 2),
  }))
  jsonError.value = ''
}, { immediate: true })

function handleAddOverride() {
  overrideDraft.value = [
    ...overrideDraft.value,
    {
      override_id: `override-${Date.now()}`,
      domain_id: props.domain.domain_id,
      service_name: 'ui',
      config_scope: 'default',
      config_json: {},
      version_tag: 'draft',
      jsonText: '{}',
    },
  ]
}

function handleRemoveOverride(overrideId: string) {
  overrideDraft.value = overrideDraft.value.filter(item => item.override_id !== overrideId)
}

function formatJson(item: OverrideDraft) {
  try {
    const parsed = JSON.parse(item.jsonText || '{}')
    item.jsonText = JSON.stringify(parsed, null, 2)
    jsonError.value = ''
  } catch {
    jsonError.value = 'JSON 格式错误，请检查输入'
  }
}

function handleSaveOverrides() {
  jsonError.value = ''
  try {
    const payload = overrideDraft.value.map(item => ({
      override_id: item.override_id,
      domain_id: props.domain.domain_id,
      service_name: item.service_name,
      config_scope: item.config_scope,
      config_json: JSON.parse(item.jsonText || '{}'),
      version_tag: item.version_tag,
    }))
    emit('saveOverrides', payload)
  } catch {
    jsonError.value = 'JSON 解析失败，请检查所有 override 的 JSON 格式'
  }
}
</script>

<style scoped>
.settings-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  border: 1px solid var(--kb-border-light);
  box-shadow: var(--kb-shadow-card);
  padding: 18px 20px;
}

.card-heading {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.empty-state {
  padding: 40px 0;
  text-align: center;
  color: var(--kb-text-tertiary);
  font-size: 13px;
}

.override-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.override-item {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 14px;
  background: #fff;
}

.override-item__head {
  display: grid;
  grid-template-columns: 130px 1fr 110px auto;
  gap: 10px;
  margin-bottom: 10px;
}

.override-item__svc {
  width: 100%;
}

.override-item__editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.error-banner {
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.15);
  border-radius: var(--kb-radius);
  color: var(--kb-danger);
  font-size: 13px;
}

@media (max-width: 960px) {
  .override-item__head {
    grid-template-columns: 1fr;
  }
}
</style>
