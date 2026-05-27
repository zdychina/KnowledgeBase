<template>
  <div class="settings-view">
    <div class="settings-view__header">
      <div class="settings-view__title-wrap">
        <h2 class="settings-view__title">配置管理中台</h2>
        <span class="settings-view__scope">当前知识域：{{ domainStore.currentDomain }}</span>
      </div>
      <div class="settings-view__actions">
        <el-button type="primary" :loading="controlPlane.bootstrapping" @click="handleBootstrap">
          导入现状
        </el-button>
        <el-button :loading="controlPlane.loading" @click="handleRefresh">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <div v-if="controlPlane.error" class="settings-view__alert settings-view__alert--danger">
      {{ controlPlane.error }}
    </div>

    <div class="settings-view__layout">
      <DomainSidebar
        :domains="controlPlane.domains"
        :selected-domain-id="controlPlane.selectedDomainId"
        @select="controlPlane.loadDomain"
      />

      <div class="settings-view__main">
        <div v-if="!controlPlane.selectedDomain" class="settings-card">
          <div class="settings-empty">
            先导入现状，再选择一个 Domain 开始管理。
          </div>
        </div>

        <template v-else>
          <DomainOverview
            :domain="controlPlane.selectedDomain"
            :bindings="controlPlane.selectedDomain.service_bindings"
            :diff-items="controlPlane.diffItems"
          />

          <el-tabs v-model="activeTab" class="settings-view__tabs">
            <el-tab-pane name="domain">
              <template #label>Domain</template>
              <DomainConfigTab
                :domain="controlPlane.selectedDomain"
                @save-domain="handleSaveDomain"
                @save-capabilities="handleSaveCapabilities"
              />
            </el-tab-pane>

            <el-tab-pane name="bindings">
              <template #label>Bindings</template>
              <BindingsTab
                :domain="controlPlane.selectedDomain"
                :service-instances="controlPlane.serviceInstances"
                @save-service-bindings="handleSaveBindings"
                @save-database-bindings="handleSaveDatabaseBindings"
              />
            </el-tab-pane>

            <el-tab-pane name="overrides">
              <template #label>Overrides</template>
              <OverridesTab
                :domain="controlPlane.selectedDomain"
                @save-overrides="handleSaveOverrides"
              />
            </el-tab-pane>

            <el-tab-pane name="runtime">
              <template #label>运行态</template>
              <RuntimeTab
                ref="runtimeTabRef"
                :observations="controlPlane.observations"
                :diff-items="controlPlane.diffItems"
                :current-config="domainStore.currentConfig"
                @check-health="checkHealth"
              />
            </el-tab-pane>

            <el-tab-pane name="legacy">
              <template #label>本地兼容</template>
              <LegacyTab />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useControlPlaneStore } from '@/stores/controlPlane'
import { useDomainStore } from '@/stores/domain'
import { useMiningApi } from '@/api/mining'
import { useServingApi } from '@/api/serving'
import { useLlmApi } from '@/api/llm'
import type {
  ControlPlaneCapability,
  ControlPlaneDatabaseBinding,
  ControlPlaneDomainDetail,
  ControlPlaneRuntimeOverride,
  ControlPlaneServiceBinding,
} from '@/types'

import DomainSidebar from '@/components/settings/DomainSidebar.vue'
import DomainOverview from '@/components/settings/DomainOverview.vue'
import DomainConfigTab from '@/components/settings/DomainConfigTab.vue'
import BindingsTab from '@/components/settings/BindingsTab.vue'
import OverridesTab from '@/components/settings/OverridesTab.vue'
import RuntimeTab from '@/components/settings/RuntimeTab.vue'
import LegacyTab from '@/components/settings/LegacyTab.vue'

const activeTab = ref('domain')
const controlPlane = useControlPlaneStore()
const domainStore = useDomainStore()
const runtimeTabRef = ref<InstanceType<typeof RuntimeTab> | null>(null)

async function handleBootstrap() {
  try {
    await controlPlane.bootstrapImport()
    ElMessage.success('已导入当前现状')
  } catch {
    ElMessage.error('导入失败')
  }
}

async function handleRefresh() {
  await controlPlane.loadDomains()
  await checkHealth()
}

async function handleSaveDomain(payload: Partial<ControlPlaneDomainDetail>) {
  try {
    await controlPlane.saveDomainPatch(payload)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

async function handleSaveCapabilities(capabilities: ControlPlaneCapability[]) {
  try {
    await controlPlane.saveCapabilities(capabilities)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

async function handleSaveBindings(bindings: ControlPlaneServiceBinding[]) {
  try {
    await controlPlane.saveServiceBindings(bindings)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

async function handleSaveDatabaseBindings(bindings: ControlPlaneDatabaseBinding[]) {
  try {
    await controlPlane.saveDatabaseBindings(bindings)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

async function handleSaveOverrides(overrides: ControlPlaneRuntimeOverride[]) {
  try {
    await controlPlane.saveOverrides(overrides)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('Overrides JSON 非法或保存失败')
  }
}

async function checkHealth() {
  const miningApi = useMiningApi()
  const servingApi = useServingApi()
  const llmApi = useLlmApi()

  const results = await Promise.all([
    miningApi.getHealth().then(() => 'up' as const).catch(() => 'down' as const),
    servingApi.getHealth().then(() => 'up' as const).catch(() => 'down' as const),
    llmApi.getHealth().then(() => 'up' as const).catch(() => 'down' as const),
  ])

  runtimeTabRef.value?.updateHealthStatus(results)
}

onMounted(async () => {
  await controlPlane.loadDomains()
  await checkHealth()
})
</script>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.settings-view__title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.settings-view__title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  color: var(--kb-text-primary);
  letter-spacing: -0.2px;
}

.settings-view__scope {
  font-size: 12px;
  color: var(--kb-text-tertiary);
}

.settings-view__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.settings-view__alert {
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  font-size: 13px;
  border: 1px solid transparent;
}

.settings-view__alert--danger {
  background: rgba(239, 68, 68, 0.06);
  border-color: rgba(239, 68, 68, 0.15);
  color: var(--kb-danger);
}

.settings-view__layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.settings-view__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.settings-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  border: 1px solid var(--kb-border-light);
  box-shadow: var(--kb-shadow-card);
  padding: 20px 22px;
}

.settings-empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--kb-text-tertiary);
  font-size: 14px;
  text-align: center;
}

.settings-view__tabs {
  background: var(--kb-bg-card);
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  box-shadow: var(--kb-shadow-card);
  padding: 0 20px 20px;
}

.settings-view__tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

@media (max-width: 960px) {
  .settings-view__layout {
    grid-template-columns: 1fr;
  }

  .settings-view__header {
    flex-direction: column;
    align-items: stretch;
  }

  .settings-view__actions {
    justify-content: flex-end;
  }
}
</style>
