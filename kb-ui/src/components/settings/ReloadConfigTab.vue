<template>
  <div class="reload-config-tab">
    <div class="reload-config-tab__hint">
      修改系统配置 YAML 后，点击对应服务的重载按钮使配置生效。不支持热切换的参数（host / port）需重启服务。
    </div>

    <div class="reload-config-tab__services">
      <div class="reload-config-tab__card">
        <div class="reload-config-tab__card-header">
          <span class="reload-config-tab__card-name">LLM Service</span>
          <el-button
            type="primary"
            size="small"
            :loading="store.reloading"
            @click="handleReload('llm')"
          >
            重载配置
          </el-button>
        </div>
        <div v-if="store.reloadResult" class="reload-config-tab__result">
          <template v-if="store.reloadResult.ok">
            <span class="reload-config-tab__ok">重载成功</span>
            <span class="reload-config-tab__detail">
              model={{ store.reloadResult.config?.provider_model }}
              concurrency={{ store.reloadResult.config?.worker_concurrency }}
            </span>
          </template>
          <span v-else class="reload-config-tab__err">{{ store.reloadResult.error }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useControlPlaneStore } from '@/stores/controlPlane'

const store = useControlPlaneStore()

async function handleReload(serviceName: string) {
  await store.reloadService(serviceName)
  if (store.reloadResult?.ok) {
    ElMessage.success('配置已重载')
  } else {
    ElMessage.error(store.reloadResult?.error ?? '重载失败')
  }
}
</script>

<style scoped>
.reload-config-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.reload-config-tab__hint {
  font-size: 13px;
  color: var(--kb-text-secondary);
  line-height: 1.6;
  padding: 0 4px;
}

.reload-config-tab__services {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.reload-config-tab__card {
  border: 1px solid var(--kb-border-light);
  border-radius: var(--kb-radius);
  padding: 14px 16px;
}

.reload-config-tab__card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.reload-config-tab__card-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--kb-text-primary);
}

.reload-config-tab__result {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--kb-border-light);
  font-size: 13px;
}

.reload-config-tab__ok {
  color: var(--el-color-success);
  font-weight: 500;
}

.reload-config-tab__detail {
  margin-left: 12px;
  color: var(--kb-text-secondary);
}

.reload-config-tab__err {
  color: var(--kb-danger);
}
</style>
