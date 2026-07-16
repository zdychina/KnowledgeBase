<template>
  <div class="opnode" :class="[`opnode--${def?.category}`, { 'opnode--output': isOutput, 'opnode--selected': selected }]">
    <div class="opnode__header">
      <span class="opnode__title">{{ def?.displayName ?? data.operatorType }}</span>
      <span class="opnode__type">{{ data.operatorType }}</span>
      <span v-if="paramSummary" class="opnode__params">{{ paramSummary }}</span>
    </div>

    <div class="opnode__body">
      <div class="opnode__col opnode__col--in">
        <div v-for="s in inputs" :key="'in-' + s.name" class="opnode__slot opnode__slot--in">
          <Handle :id="s.name" type="target" :position="Position.Left" class="opnode__handle" />
          <span class="opnode__slot-label">{{ s.name }}</span>
        </div>
      </div>
      <div class="opnode__col opnode__col--out">
        <div v-for="s in outputs" :key="'out-' + s.name" class="opnode__slot opnode__slot--out">
          <span class="opnode__slot-label">{{ s.name }}</span>
          <Handle :id="s.name" type="source" :position="Position.Right" class="opnode__handle opnode__handle--out" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { OperatorDef, SlotDecl } from '@/types/operator'

const props = defineProps<{
  id: string
  data: { operatorType: string; def?: OperatorDef; isOutput?: boolean; params?: Record<string, unknown> }
  selected?: boolean
}>()

const def = computed(() => props.data.def)
const inputs = computed<SlotDecl[]>(() => def.value?.inputSlots ?? [])
const outputs = computed<SlotDecl[]>(() => def.value?.outputSlots ?? [])
const isOutput = computed(() => props.data.isOutput ?? false)

/** Short summary of scalar params shown on the node, e.g. "textKind=both · topK=20". */
const paramSummary = computed(() => {
  const parts: string[] = []
  for (const [k, v] of Object.entries(props.data.params ?? {})) {
    if (v === null || v === undefined || v === '' || typeof v === 'object') continue
    parts.push(`${k}=${v}`)
  }
  return parts.slice(0, 3).join(' · ')
})
</script>

<style scoped>
.opnode {
  min-width: 180px; border-radius: 9px; background: #fff;
  border: 1px solid #e5e7eb; border-top: 3px solid var(--cat, #94a3b8);
  box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 12px;
}
.opnode--output { box-shadow: 0 0 0 2px #22c55e55, 0 1px 4px rgba(0,0,0,.08); }
.opnode--input { --cat: #0ea5e9; }
.opnode--query { --cat: #6366f1; }
.opnode--scope { --cat: #14b8a6; }
.opnode--retrieve { --cat: #3b82f6; }
.opnode--fuse { --cat: #f59e0b; }
.opnode--rerank { --cat: #ec4899; }
.opnode--output { --cat: #22c55e; }
/* selected state — distinct blue ring; declared after --output so it wins when both apply */
.opnode--selected { border-color: #3b82f6; box-shadow: 0 0 0 2px #3b82f6, 0 6px 18px rgba(59,130,246,.30); }

.opnode__header { padding: 7px 12px 6px; display: flex; flex-direction: column; gap: 1px; }
.opnode__title { font-weight: 700; color: #1e293b; line-height: 1.2; }
.opnode__type { font-size: 10px; color: #94a3b8; font-family: monospace; line-height: 1.2; }
.opnode__params { font-size: 10px; color: #64748b; line-height: 1.3; margin-top: 2px; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.opnode__body { display: flex; justify-content: space-between; gap: 16px; padding: 4px 0 9px; }
.opnode__col { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }

/* Each slot row is the positioning context, so the Handle (default top:50%) centers on THIS row. */
.opnode__slot { position: relative; height: 22px; display: flex; align-items: center; white-space: nowrap; }
.opnode__slot--in { justify-content: flex-start; padding-left: 12px; }
.opnode__slot--out { justify-content: flex-end; padding-right: 12px; }
.opnode__slot-label { font-size: 11px; color: #475569; }

.opnode__handle { width: 9px; height: 9px; background: #64748b; border: 2px solid #fff; }
.opnode__handle--out { background: #3b82f6; }
</style>
