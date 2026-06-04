<template>
  <div class="code-sync-tab">
    <div class="code-sync-tab__hint">
      从 GitHub 拉取最新 Python 服务代码到运行目录。同步后需手动重启服务生效。
      <br />
      <strong>注意</strong>：仅更新代码文件，不会覆盖配置（.env、scenario_packs、databases 等）。
    </div>

    <div class="code-sync-tab__dirs">
      <span class="code-sync-tab__dirs-label">可同步目录：</span>
      <el-tag v-for="d in SYNC_DIRS" :key="d" size="small" type="info" class="code-sync-tab__tag">
        {{ d }}/
      </el-tag>
      <el-tag size="small" type="warning" class="code-sync-tab__tag">
        main_control_service/config/ (不覆盖)
      </el-tag>
    </div>

    <div class="code-sync-tab__action">
      <el-button type="primary" :loading="store.syncing" @click="handleSync">
        同步最新代码
      </el-button>
    </div>

    <div v-if="store.syncResult" class="code-sync-tab__result">
      <template v-if="store.syncResult.ok">
        <div class="code-sync-tab__ok">
          同步成功！共更新 {{ store.syncResult.file_count }} 个文件。
        </div>
        <div class="code-sync-tab__detail">
          更新目录：{{ store.syncResult.updated_dirs?.join('、') }}
        </div>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          class="code-sync-tab__alert"
        >
          代码已更新，请手动重启服务使新代码生效。
        </el-alert>
      </template>
      <div v-else class="code-sync-tab__err">
        同步失败：{{ store.syncResult.error }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useControlPlaneStore } from '@/stores/controlPlane'

const store = useControlPlaneStore()

const SYNC_DIRS = ['knowledge_mining', 'llm_service', 'main_control_service', 'mcp_server']

async function handleSync() {
  await store.syncCode()
  if (store.syncResult?.ok) {
    ElMessage.success('代码同步完成')
  } else {
    ElMessage.error(store.syncResult?.error ?? '同步失败')
  }
}
</script>

<style scoped>
.code-sync-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.code-sync-tab__hint {
  font-size: 13px;
  color: var(--kb-text-secondary);
  line-height: 1.6;
  padding: 0 4px;
}

.code-sync-tab__dirs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.code-sync-tab__dirs-label {
  font-size: 13px;
  color: var(--kb-text-secondary);
}

.code-sync-tab__tag {
  font-family: monospace;
}

.code-sync-tab__action {
  padding-top: 4px;
}

.code-sync-tab__result {
  border-top: 1px solid var(--kb-border-light);
  padding-top: 14px;
}

.code-sync-tab__ok {
  color: var(--el-color-success);
  font-weight: 500;
  font-size: 14px;
}

.code-sync-tab__detail {
  margin-top: 6px;
  font-size: 13px;
  color: var(--kb-text-secondary);
}

.code-sync-tab__alert {
  margin-top: 12px;
}

.code-sync-tab__err {
  color: var(--kb-danger);
  font-size: 14px;
}
</style>
