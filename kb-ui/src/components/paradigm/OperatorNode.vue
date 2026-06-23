<template>
  <div class="opnode" :class="[`opnode--${def?.category}`, { 'opnode--output': isOutput }]">
    <div class="opnode__header">
      <span class="opnode__title">{{ def?.displayName ?? data.operatorType }}</span>
      <span class="opnode__type">{{ data.operatorType }}</span>
    </div>

    <div class="opnode__body">
      <div class="opnode__col">
        <div v-for="(s, i) in inputs" :key="'in-' + s.name" class="opnode__slot opnode__slot--in">
          <Handle
            :id="s.name"
            type="target"
            :position="Position.Left"
            :style="{ top: handleTop(i) }"
            class="opnode__handle"
          />
          <span class="opnode__slot-label">{{ s.name }}</span>
        </div>
      </div>
      <div class="opnode__col opnode__col--out">
        <div v-for="(s, i) in outputs" :key="'out-' + s.name" class="opnode__slot opnode__slot--out">
          <span class="opnode__slot-label">{{ s.name }}</span>
          <Handle
            :id="s.name"
            type="source"
            :position="Position.Right"
            :style="{ top: handleTop(i) }"
            class="opnode__handle opnode__handle--out"
          />
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
  data: { operatorType: string; def?: OperatorDef; isOutput?: boolean }
}>()

const def = computed(() => props.data.def)
const inputs = computed<SlotDecl[]>(() => def.value?.inputSlots ?? [])
const outputs = computed<SlotDecl[]>(() => def.value?.outputSlots ?? [])
const isOutput = computed(() => props.data.isOutput ?? false)

const HEADER = 34
const ROW = 24
function handleTop(i: number): string {
  return `${HEADER + ROW / 2 + i * ROW}px`
}
</script>

<style scoped>
.opnode {
  min-width: 170px; border-radius: 9px; background: #fff;
  border: 1px solid #e5e7eb; border-top: 3px solid var(--cat, #94a3b8);
  box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 12px;
}
.opnode--output { box-shadow: 0 0 0 2px #22c55e55, 0 1px 4px rgba(0,0,0,.08); }
.opnode--query { --cat: #6366f1; }
.opnode--scope { --cat: #14b8a6; }
.opnode--retrieve { --cat: #3b82f6; }
.opnode--fuse { --cat: #f59e0b; }
.opnode--rerank { --cat: #ec4899; }
.opnode--output { --cat: #22c55e; }
.opnode__header { padding: 7px 12px 5px; display: flex; flex-direction: column; gap: 1px; }
.opnode__title { font-weight: 700; color: #1e293b; }
.opnode__type { font-size: 10px; color: #94a3b8; font-family: monospace; }
.opnode__body { display: flex; justify-content: space-between; padding: 4px 0 8px; }
.opnode__col { display: flex; flex-direction: column; gap: 0; }
.opnode__col--out { align-items: flex-end; }
.opnode__slot { position: relative; height: 24px; display: flex; align-items: center; padding: 0 12px; }
.opnode__slot-label { font-size: 11px; color: #475569; }
.opnode__handle { width: 9px; height: 9px; background: #64748b; border: 2px solid #fff; }
.opnode__handle--out { background: #3b82f6; }
</style>
