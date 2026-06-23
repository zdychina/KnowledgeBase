<template>
  <div class="palette">
    <div class="palette__hint">拖拽算子到画布</div>
    <div v-for="group in groups" :key="group.category" class="palette__group">
      <div class="palette__group-title">{{ categoryLabel(group.category) }}</div>
      <div
        v-for="op in group.ops"
        :key="op.type"
        class="palette__item"
        :class="`palette__item--${op.category}`"
        draggable="true"
        @dragstart="onDragStart($event, op.type)"
      >
        <span class="palette__item-name">{{ op.displayName }}</span>
        <span class="palette__item-type">{{ op.type }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { OperatorDef } from '@/types/operator'

const props = defineProps<{ operators: OperatorDef[] }>()

const CATEGORY_ORDER = ['input', 'query', 'scope', 'retrieve', 'fuse', 'rerank', 'output']
const CATEGORY_LABELS: Record<string, string> = {
  input: '入口', query: '查询变换', scope: '范围', retrieve: '检索',
  fuse: '融合', rerank: '重排', output: '输出',
}

const groups = computed(() => {
  const byCat = new Map<string, OperatorDef[]>()
  for (const op of props.operators) {
    if (!byCat.has(op.category)) byCat.set(op.category, [])
    byCat.get(op.category)!.push(op)
  }
  const cats = [...byCat.keys()].sort(
    (a, b) => (CATEGORY_ORDER.indexOf(a) + 100) % 100 - ((CATEGORY_ORDER.indexOf(b) + 100) % 100),
  )
  return cats.map(category => ({ category, ops: byCat.get(category)! }))
})

function categoryLabel(c: string): string {
  return CATEGORY_LABELS[c] ?? c
}

function onDragStart(e: DragEvent, type: string) {
  e.dataTransfer?.setData('application/operator-type', type)
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
</script>

<style scoped>
.palette { display: flex; flex-direction: column; gap: 14px; padding: 4px; }
.palette__hint { font-size: 11px; color: var(--kb-text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; }
.palette__group { display: flex; flex-direction: column; gap: 5px; }
.palette__group-title { font-size: 12px; font-weight: 700; color: var(--kb-text-secondary); margin-bottom: 2px; }
.palette__item {
  display: flex; flex-direction: column; gap: 1px;
  padding: 7px 10px; border-radius: 7px; cursor: grab;
  background: var(--kb-bg-elevated, #fff); border: 1px solid var(--kb-border, #e5e7eb);
  border-left: 3px solid var(--cat-color, #94a3b8);
  transition: all .12s ease;
}
.palette__item:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); transform: translateY(-1px); }
.palette__item:active { cursor: grabbing; }
.palette__item-name { font-size: 13px; font-weight: 600; color: var(--kb-text-primary); }
.palette__item-type { font-size: 10.5px; color: var(--kb-text-tertiary); font-family: monospace; }
.palette__item--input { --cat-color: #0ea5e9; }
.palette__item--query { --cat-color: #6366f1; }
.palette__item--scope { --cat-color: #14b8a6; }
.palette__item--retrieve { --cat-color: #3b82f6; }
.palette__item--fuse { --cat-color: #f59e0b; }
.palette__item--rerank { --cat-color: #ec4899; }
.palette__item--output { --cat-color: #22c55e; }
</style>
