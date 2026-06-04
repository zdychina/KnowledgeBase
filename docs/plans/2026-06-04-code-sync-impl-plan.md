# Python 服务代码同步 — 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在前端系统设置页增加"代码同步"功能，一键从 GitHub 拉取最新 Python 代码覆盖到运行目录。

**Architecture:** main_control_service 新增 `CodeSyncService` 类（独立于 YamlConfigService），负责下载 GitHub tarball 并解压覆盖白名单目录。前端新增 `CodeSyncTab` 组件。API 端点 `POST /api/v1/code-sync` 注册在 `main.py`。

**Tech Stack:** Python 3.11 + tarfile + urllib + FastAPI, Vue 3 + Element Plus + TypeScript

---

### Task 1: 后端 — 新建 CodeSyncService

**Files:**
- Create: `main_control_service/code_sync.py`
- Test: `main_control_service/tests/test_code_sync.py`（手动测试即可，无 pytest 基础设施）

**Step 1: 创建 code_sync.py**

```python
"""GitHub Archive API 代码同步服务。

从 https://github.com/fzl194/KnowledgeBase/archive/refs/heads/master.tar.gz
下载最新 tarball，只解压白名单目录到 /app/。
"""
from __future__ import annotations

import logging
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://github.com/fzl194/KnowledgeBase/archive/refs/heads/master.tar.gz"

# 白名单：只覆盖这些目录
SYNC_DIRS = {"knowledge_mining", "llm_service", "main_control_service", "mcp_server"}

# 排除的子目录（即使是白名单目录内也不覆盖）
EXCLUDE_SUBDIRS = {"main_control_service/config"}

DOWNLOAD_TIMEOUT = 60


@dataclass(slots=True)
class CodeSyncResult:
    ok: bool
    updated_dirs: list[str]
    file_count: int
    error: str | None = None


def sync_from_github(app_dir: Path | None = None) -> CodeSyncResult:
    """从 GitHub 下载最新 tarball 并解压白名单目录。

    Args:
        app_dir: 目标根目录，默认 /app
    """
    target_root = app_dir or Path("/app")
    tmp_path = Path(tempfile.gettempdir()) / f"cmkb-sync-{int(time.time())}.tar.gz"

    # 1. 下载
    try:
        logger.info("Downloading %s", ARCHIVE_URL)
        urllib.request.urlretrieve(ARCHIVE_URL, tmp_path)
        logger.info("Downloaded to %s (%.1f KB)", tmp_path, tmp_path.stat().st_size / 1024)
    except Exception as e:
        logger.error("Download failed: %s", e)
        return CodeSyncResult(ok=False, updated_dirs=[], file_count=0, error=f"下载失败: {e}")
        if tmp_path.exists():
            tmp_path.unlink()

    # 2. 解压
    updated_dirs: set[str] = set()
    file_count = 0

    try:
        with tarfile.open(tmp_path, "r:gz") as tar:
            for member in tar.getmembers():
                # 路径遍历检查
                if ".." in member.name:
                    continue

                # tarball 路径格式: KnowledgeBase-master/{dir}/...
                parts = Path(member.name).parts
                if len(parts) < 3:
                    continue  # 根目录或单层文件

                # parts[0] = "KnowledgeBase-master", parts[1] = dir name
                dir_name = parts[1]

                if dir_name not in SYNC_DIRS:
                    continue

                # 排除检查: main_control_service/config/...
                rel_after_dir = "/".join(parts[2:])
                exclude_key = f"{dir_name}/{rel_after_dir.split('/')[0]}" if "/" in rel_after_dir else ""
                if exclude_key in EXCLUDE_SUBDIRS:
                    continue

                # 只处理文件（跳过目录条目）
                if not member.isfile():
                    continue

                # 提取到目标目录
                dest = target_root / dir_name / rel_after_dir
                dest.parent.mkdir(parents=True, exist_ok=True)

                with tar.extractfile(member) as src:
                    if src:
                        dest.write_bytes(src.read())

                updated_dirs.add(dir_name)
                file_count += 1

    except Exception as e:
        logger.error("Extract failed: %s", e)
        return CodeSyncResult(ok=False, updated_dirs=list(updated_dirs), file_count=file_count, error=f"解压失败: {e}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    logger.info("Sync complete: %d files in %s", file_count, updated_dirs)
    return CodeSyncResult(ok=True, updated_dirs=sorted(updated_dirs), file_count=file_count)
```

**Step 2: 验证模块可导入**

Run: `cd /d D:\mywork\KnowledgeBase\CoreMasterKB && python -c "from main_control_service.code_sync import sync_from_github, CodeSyncResult; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add main_control_service/code_sync.py
git commit -m "[claude]: add CodeSyncService for GitHub archive sync"
```

---

### Task 2: 后端 — 在 main.py 注册 API 端点

**Files:**
- Modify: `main_control_service/main.py` (在 `create_app` 函数内新增端点)

**Step 1: 添加 code-sync 端点**

在 `main.py` 的 `create_app` 函数内，`reverse_proxy` 路由之前，新增：

```python
    # ------------------------------------------------------------------
    # Code sync — GitHub archive -> local Python services
    # ------------------------------------------------------------------

    @app.post("/api/v1/code-sync")
    def sync_code() -> dict:
        from main_control_service.code_sync import sync_from_github

        result = sync_from_github()
        return {
            "ok": result.ok,
            "updated_dirs": result.updated_dirs,
            "file_count": result.file_count,
            **({"error": result.error} if result.error else {}),
        }
```

**Step 2: 验证端点可访问**

Run: `python -c "from main_control_service.main import create_app; app = create_app(); routes = [r.path for r in app.routes]; print('/api/v1/code-sync' in routes)"`
Expected: `True`

**Step 3: Commit**

```bash
git add main_control_service/main.py
git commit -m "[claude]: add POST /api/v1/code-sync endpoint"
```

---

### Task 3: 前端 — API 层新增 codeSync 方法

**Files:**
- Modify: `kb-ui/src/api/controlPlane.ts` (新增 codeSync 方法)
- Modify: `kb-ui/src/api/controlPlane.ts` (新增类型)

**Step 1: 添加类型和 API 方法**

在 `controlPlane.ts` 文件末尾（`ServiceReloadResult` interface 之后）新增：

```typescript
export interface CodeSyncResult {
  ok: boolean
  updated_dirs?: string[]
  file_count?: number
  error?: string
}
```

在 `useControlPlaneApi()` return 对象内新增：

```typescript
    // ── Code sync ──
    async codeSync(): Promise<CodeSyncResult> {
      const { data } = await client.post('/api/v1/code-sync')
      return data
    },
```

**Step 2: 验证编译**

Run: `cd kb-ui && npx vue-tsc --noEmit`
Expected: 无错误

**Step 3: Commit**

```bash
git add kb-ui/src/api/controlPlane.ts
git commit -m "[claude]: add codeSync API method and type"
```

---

### Task 4: 前端 — Store 新增 sync 状态和 action

**Files:**
- Modify: `kb-ui/src/stores/controlPlane.ts`

**Step 1: 添加 sync 状态和 action**

在 store 内（`reloadResult` ref 之后）新增：

```typescript
  // ── Code sync ──
  const syncing = ref(false)
  const syncResult = ref<CodeSyncResult | null>(null)
```

在 `reloadService` action 之后新增：

```typescript
  // ── Code sync action ──
  async function syncCode() {
    syncing.value = true
    syncResult.value = null
    try {
      syncResult.value = await api.codeSync()
    } catch (err) {
      syncResult.value = { ok: false, error: err instanceof Error ? err.message : 'Sync failed' }
    } finally {
      syncing.value = false
    }
  }
```

在 return 对象内新增 `syncing`, `syncResult`, `syncCode`。

同时在文件顶部 import `CodeSyncResult` 类型：

```typescript
import { useControlPlaneApi } from '@/api/controlPlane'
import type { CodeSyncResult } from '@/api/controlPlane'
```

**Step 2: 验证编译**

Run: `cd kb-ui && npx vue-tsc --noEmit`
Expected: 无错误

**Step 3: Commit**

```bash
git add kb-ui/src/stores/controlPlane.ts
git commit -m "[claude]: add code sync state and action to controlPlane store"
```

---

### Task 5: 前端 — 新建 CodeSyncTab 组件

**Files:**
- Create: `kb-ui/src/components/settings/CodeSyncTab.vue`

**Step 1: 创建组件**

```vue
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
```

**Step 2: 验证编译**

Run: `cd kb-ui && npx vue-tsc --noEmit`
Expected: 无错误

**Step 3: Commit**

```bash
git add kb-ui/src/components/settings/CodeSyncTab.vue
git commit -m "[claude]: add CodeSyncTab component"
```

---

### Task 6: 前端 — 注册 CodeSyncTab 到 SettingsView

**Files:**
- Modify: `kb-ui/src/views/SettingsView.vue`

**Step 1: 添加新 tab**

在 `<el-tab-pane label="配置重载" name="reload">` 之后新增：

```html
        <el-tab-pane label="代码同步" name="sync">
          <CodeSyncTab />
        </el-tab-pane>
```

在 `<script setup>` 内新增 import：

```typescript
import CodeSyncTab from '@/components/settings/CodeSyncTab.vue'
```

**Step 2: 验证编译**

Run: `cd kb-ui && npx vue-tsc --noEmit`
Expected: 无错误

**Step 3: Commit**

```bash
git add kb-ui/src/views/SettingsView.vue
git commit -m "[claude]: add code sync tab to settings view"
```

---

### Task 7: 端到端验证

**Step 1: 启动主控服务**

Run: `cd D:\mywork\KnowledgeBase\CoreMasterKB && python -m main_control_service.main`

**Step 2: 测试 API 端点**

Run: `curl -X POST http://localhost:8910/api/v1/code-sync`

Expected: 返回 JSON `{ "ok": true, "updated_dirs": [...], "file_count": N }`

**Step 3: 验证前端页面**

打开 `http://localhost:5173`（或前端 dev server），进入系统设置 → 代码同步 tab，点击按钮，确认 UI 正常。

**Step 4: 最终提交（如有修复）**

```bash
git add -A
git commit -m "[claude]: finalize code sync feature"
```
