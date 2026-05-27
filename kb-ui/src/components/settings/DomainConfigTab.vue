<template>
  <div class="config-grid">
    <section class="settings-card">
      <h3 class="card-heading">基础配置</h3>

      <el-form label-position="top" class="stack-form">
        <div class="stack-form__grid">
          <el-form-item label="Domain ID">
            <el-input :model-value="domainDraft.domain_id" disabled />
          </el-form-item>
          <el-form-item label="显示名">
            <el-input v-model="domainDraft.display_name" />
          </el-form-item>
          <el-form-item label="默认 Channel">
            <el-input v-model="domainDraft.default_channel" />
          </el-form-item>
          <el-form-item label="Scenario Pack">
            <el-input v-model="domainDraft.scenario_pack_ref" />
          </el-form-item>
        </div>

        <el-form-item label="描述">
          <el-input v-model="domainDraft.description" type="textarea" :rows="4" />
        </el-form-item>

        <div class="form-actions">
          <div class="form-switch">
            <el-switch v-model="domainDraft.enabled" />
            <span>启用 Domain</span>
          </div>
          <el-button type="primary" @click="handleSaveDomain">保存基础配置</el-button>
        </div>
      </el-form>
    </section>

    <section class="settings-card">
      <h3 class="card-heading">Capability</h3>

      <div class="cap-list">
        <div v-for="cap in capabilityDraft" :key="cap.service_name" class="cap-item">
          <div class="cap-item__body">
            <strong class="cap-item__name">{{ cap.service_name }}</strong>
            <span class="cap-item__state">{{ cap.rollout_state || 'active' }}</span>
          </div>
          <el-switch v-model="cap.enabled" />
        </div>
      </div>

      <div class="card-footer">
        <el-button type="primary" @click="handleSaveCapabilities">保存 Capability</el-button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ControlPlaneCapability, ControlPlaneDomainDetail } from '@/types'

const props = defineProps<{
  domain: ControlPlaneDomainDetail
}>()

const emit = defineEmits<{
  saveDomain: [payload: Partial<ControlPlaneDomainDetail>]
  saveCapabilities: [capabilities: ControlPlaneCapability[]]
}>()

const domainDraft = ref<ControlPlaneDomainDetail>(createEmptyDraft())
const capabilityDraft = ref<ControlPlaneCapability[]>([])

watch(() => props.domain, (val) => {
  if (!val) {
    domainDraft.value = createEmptyDraft()
    capabilityDraft.value = []
    return
  }
  domainDraft.value = JSON.parse(JSON.stringify(val))
  capabilityDraft.value = val.capabilities.map(c => ({ ...c }))
}, { immediate: true })

function createEmptyDraft(): ControlPlaneDomainDetail {
  return {
    domain_id: '',
    display_name: '',
    enabled: false,
    default_channel: 'prod',
    scenario_pack_ref: '',
    description: '',
    owner_team: '',
    metadata_json: {},
    created_at: '',
    updated_at: '',
    capabilities: [],
    service_bindings: [],
    database_bindings: [],
    overrides: [],
  }
}

function handleSaveDomain() {
  emit('saveDomain', {
    display_name: domainDraft.value.display_name,
    enabled: domainDraft.value.enabled,
    default_channel: domainDraft.value.default_channel,
    scenario_pack_ref: domainDraft.value.scenario_pack_ref,
    description: domainDraft.value.description,
  })
}

function handleSaveCapabilities() {
  emit('saveCapabilities', capabilityDraft.value)
}
</script>

<style scoped>
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.settings-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  border: 1px solid var(--kb-border-light);
  box-shadow: var(--kb-shadow-card);
  padding: 18px 20px;
}

.card-heading {
  margin: 0 0 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.stack-form__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
}

.form-switch {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--kb-text-secondary);
  font-size: 13px;
}

.cap-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cap-item {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.cap-item__body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.cap-item__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.cap-item__state {
  font-size: 11px;
  color: var(--kb-text-tertiary);
}

@media (max-width: 1280px) {
  .config-grid {
    grid-template-columns: 1fr;
  }
}
</style>
