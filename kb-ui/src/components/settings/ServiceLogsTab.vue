<template>
  <div class="logs-tab">
    <div class="logs-tab__hint">
      查看各服务的运行日志（由 supervisor 写在 <code>{{ store.logDir || '/app/logs' }}</code>，
      单文件 50MB、保留 5 份轮转）。只读，不会修改任何文件。
      <br />
      <strong>说明</strong>：只展示当前日志文件；轮转出去的历史文件需登录服务器查看。
    </div>

    <div class="logs-tab__toolbar">
      <el-select
        v-model="store.selectedLogName"
        placeholder="选择服务"
        size="small"
        class="logs-tab__select"
        @change="refresh"
      >
        <el-option
          v-for="f in store.logFiles"
          :key="f.name"
          :label="`${f.name}（${formatSize(f.size_bytes)}）`"
          :value="f.name"
        />
      </el-select>

      <el-select v-model="level" size="small" class="logs-tab__level" @change="refresh">
        <el-option label="全部级别" value="" />
        <el-option v-for="lv in LEVELS" :key="lv" :label="`${lv} 及以上`" :value="lv" />
      </el-select>

      <el-input
        v-model="keyword"
        placeholder="关键字过滤"
        size="small"
        clearable
        class="logs-tab__keyword"
        @keyup.enter="refresh"
        @clear="refresh"
      />

      <el-select v-model="lines" size="small" class="logs-tab__lines" @change="refresh">
        <el-option v-for="n in LINE_OPTIONS" :key="n" :label="`${n} 行`" :value="n" />
      </el-select>

      <el-button size="small" :loading="store.logLoading" @click="refresh">刷新</el-button>

      <el-checkbox v-model="autoRefresh" size="small" class="logs-tab__auto">
        自动刷新（5s）
      </el-checkbox>
    </div>

    <el-alert
      v-if="store.logContent?.truncated"
      type="info"
      :closable="false"
      show-icon
      class="logs-tab__alert"
    >
      文件较大，只读取了尾部内容；过滤结果仅覆盖被读取的部分，更早的日志需登录服务器查看。
    </el-alert>

    <div v-if="store.logFiles.length === 0" class="logs-tab__empty">
      没有找到日志文件。若服务刚部署，请确认容器已挂载 <code>./logs</code> 目录。
    </div>

    <pre v-else ref="viewer" class="logs-tab__viewer"><template
      v-if="store.logContent?.lines?.length"
    ><div
        v-for="(line, i) in store.logContent.lines"
        :key="i"
        :class="['logs-tab__line', lineClass(line)]"
      >{{ line }}</div></template><span v-else class="logs-tab__none">{{
      store.logLoading ? '加载中…' : '没有匹配的日志行'
    }}</span></pre>

    <div v-if="store.logContent" class="logs-tab__status">
      显示 {{ store.logContent.returned_lines }} 行 ·
      文件大小 {{ formatSize(store.logContent.size_bytes) }}
      <span v-if="lastUpdated"> · 更新于 {{ lastUpdated }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useControlPlaneStore } from '@/stores/controlPlane'

const store = useControlPlaneStore()

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
const LINE_OPTIONS = [100, 200, 500, 1000, 2000]

const level = ref('')
const keyword = ref('')
const lines = ref(200)
const autoRefresh = ref(false)
const lastUpdated = ref('')
const viewer = ref<HTMLElement | null>(null)

let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  await store.loadLogContent({
    lines: lines.value,
    ...(keyword.value ? { q: keyword.value } : {}),
    ...(level.value ? { level: level.value } : {}),
  })
  lastUpdated.value = new Date().toLocaleTimeString()
  await nextTick()
  scrollToBottom()
}

function scrollToBottom() {
  if (viewer.value) viewer.value.scrollTop = viewer.value.scrollHeight
}

function lineClass(line: string): string {
  if (/\b(ERROR|CRITICAL)\b/.test(line)) return 'logs-tab__line--error'
  if (/\bWARNING\b/.test(line)) return 'logs-tab__line--warn'
  if (/\bDEBUG\b/.test(line)) return 'logs-tab__line--debug'
  return ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

// 自动刷新：只在开关打开时起定时器，组件卸载必须清掉，
// 否则切走页面后仍在轮询（RunDetailView 曾经踩过这个坑）。
watch(autoRefresh, (on) => {
  stopTimer()
  if (on) timer = setInterval(refresh, 5000)
})

onMounted(async () => {
  await store.loadLogFiles()
  if (store.selectedLogName) await refresh()
})

onUnmounted(stopTimer)
</script>

<style scoped>
.logs-tab {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.logs-tab__hint {
  font-size: 13px;
  color: var(--kb-text-secondary);
  line-height: 1.6;
  padding: 0 4px;
}

.logs-tab__hint code {
  font-family: monospace;
  font-size: 12px;
}

.logs-tab__toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.logs-tab__select {
  width: 220px;
}

.logs-tab__level {
  width: 140px;
}

.logs-tab__keyword {
  width: 200px;
}

.logs-tab__lines {
  width: 110px;
}

.logs-tab__auto {
  margin-left: 4px;
}

.logs-tab__viewer {
  margin: 0;
  height: 460px;
  overflow: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: var(--kb-radius);
  padding: 12px 14px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.logs-tab__line {
  white-space: pre-wrap;
  word-break: break-all;
}

.logs-tab__line--error {
  color: #f48771;
}

.logs-tab__line--warn {
  color: #dcdcaa;
}

.logs-tab__line--debug {
  color: #808080;
}

.logs-tab__none {
  color: #808080;
}

.logs-tab__empty {
  font-size: 13px;
  color: var(--kb-text-secondary);
  padding: 24px 4px;
}

.logs-tab__status {
  font-size: 12px;
  color: var(--kb-text-secondary);
}
</style>
