<template>
  <div class="bindings-grid">
    <section class="settings-card">
      <h3 class="card-heading">服务绑定</h3>

      <div class="binding-list">
        <div
          v-for="binding in bindingDraft"
          :key="binding.service_name"
          class="binding-item"
        >
          <div class="binding-item__head">
            <strong class="binding-item__name">{{ binding.service_name }}</strong>
            <span class="binding-item__meta">{{ binding.binding_mode }} / priority {{ binding.priority }}</span>
          </div>
          <el-select v-model="binding.instance_id" class="binding-item__select">
            <el-option
              v-for="instance in instancesFor(binding.service_name)"
              :key="instance.instance_id"
              :label="`${instance.display_name} · ${instance.base_url}`"
              :value="instance.instance_id"
            />
          </el-select>
        </div>
      </div>

      <div class="card-footer">
        <el-button type="primary" @click="handleSaveServiceBindings">保存服务绑定</el-button>
      </div>
    </section>

    <section class="settings-card">
      <h3 class="card-heading">数据库绑定</h3>

      <div class="db-list">
        <div
          v-for="binding in databaseDraft"
          :key="binding.binding_id"
          class="db-item"
        >
          <div class="db-item__head">
            <strong class="db-item__name">{{ binding.usage_type }}</strong>
            <span class="db-item__meta">{{ binding.driver }} / {{ binding.schema_name || 'public' }}</span>
          </div>
          <el-input v-model="binding.secret_ref" placeholder="secret ref" />
        </div>
      </div>

      <div class="card-footer">
        <el-button type="primary" @click="handleSaveDatabaseBindings">保存数据库绑定</el-button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type {
  ControlPlaneDatabaseBinding,
  ControlPlaneDomainDetail,
  ControlPlaneServiceBinding,
  ControlPlaneServiceInstance,
} from '@/types'

const props = defineProps<{
  domain: ControlPlaneDomainDetail
  serviceInstances: ControlPlaneServiceInstance[]
}>()

const emit = defineEmits<{
  saveServiceBindings: [bindings: ControlPlaneServiceBinding[]]
  saveDatabaseBindings: [bindings: ControlPlaneDatabaseBinding[]]
}>()

const bindingDraft = ref<ControlPlaneServiceBinding[]>([])
const databaseDraft = ref<ControlPlaneDatabaseBinding[]>([])

watch(() => props.domain, (val) => {
  if (!val) {
    bindingDraft.value = []
    databaseDraft.value = []
    return
  }
  bindingDraft.value = val.service_bindings.map(b => ({ ...b }))
  databaseDraft.value = val.database_bindings.map(b => ({ ...b }))
}, { immediate: true })

function instancesFor(serviceName: string) {
  return props.serviceInstances.filter(i => i.service_name === serviceName)
}

function handleSaveServiceBindings() {
  emit('saveServiceBindings', bindingDraft.value)
}

function handleSaveDatabaseBindings() {
  emit('saveDatabaseBindings', databaseDraft.value)
}
</script>

<style scoped>
.bindings-grid {
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

.binding-list,
.db-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.binding-item,
.db-item {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.binding-item__head,
.db-item__head {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.binding-item__name,
.db-item__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text-primary);
}

.binding-item__meta,
.db-item__meta {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  font-family: 'SF Mono', 'Cascadia Code', monospace;
}

.binding-item__select {
  width: 100%;
}

@media (max-width: 1280px) {
  .bindings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
