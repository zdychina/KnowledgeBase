<template>
  <div class="legacy-grid">
    <section class="settings-card">
      <h3 class="card-heading">Domain 本地配置</h3>

      <el-table :data="domainRows" class="kb-table" :header-cell-style="{ background: 'transparent' }">
        <el-table-column prop="name" label="Domain" width="160" />
        <el-table-column prop="miningApi" label="挖掘服务" min-width="160" />
        <el-table-column prop="servingApi" label="检索服务" min-width="160" />
        <el-table-column prop="llmApi" label="LLM 服务" min-width="160" />
        <el-table-column prop="active" label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.active" @change="handleToggle(row)" />
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="settings-card">
      <h3 class="card-heading">编辑当前 Domain 本地配置</h3>

      <el-form label-position="top">
        <el-form-item label="挖掘服务">
          <el-input v-model="editConfig.miningApi" />
        </el-form-item>
        <el-form-item label="检索服务">
          <el-input v-model="editConfig.servingApi" />
        </el-form-item>
        <el-form-item label="LLM 服务">
          <el-input v-model="editConfig.llmApi" />
        </el-form-item>
        <div class="card-footer">
          <el-button type="primary" @click="handleSaveLegacy">保存本地兼容配置</el-button>
        </div>
      </el-form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useDomainStore } from '@/stores/domain'
import type { DomainConfig } from '@/types'

const domainStore = useDomainStore()

const domainRows = computed(() =>
  Object.entries(domainStore.domains).map(([name, cfg]) => ({ name, ...cfg }))
)

const editConfig = ref<DomainConfig>({ ...domainStore.currentConfig })

watch(() => domainStore.currentDomain, () => {
  editConfig.value = { ...domainStore.currentConfig }
})

function handleToggle(row: { name: string; active: boolean } & DomainConfig) {
  domainStore.updateDomain(row.name, {
    miningApi: row.miningApi,
    servingApi: row.servingApi,
    llmApi: row.llmApi,
    active: row.active,
  })
}

function handleSaveLegacy() {
  domainStore.updateDomain(domainStore.currentDomain, { ...editConfig.value })
  ElMessage.success('本地兼容配置已保存')
}
</script>

<style scoped>
.legacy-grid {
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
  margin-top: 12px;
}

@media (max-width: 1280px) {
  .legacy-grid {
    grid-template-columns: 1fr;
  }
}
</style>
