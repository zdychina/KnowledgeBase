<template>
  <div class="param-form">
    <div v-if="fields.length === 0" class="param-form__empty">该算子无可配置参数</div>
    <div v-for="f in fields" :key="f.key" class="param-form__field">
      <label class="param-form__label">{{ f.title }}</label>

      <!-- enum -> select -->
      <el-select
        v-if="f.kind === 'enum'"
        :model-value="value(f.key)"
        size="small"
        style="width: 100%"
        @update:model-value="set(f.key, $event)"
      >
        <el-option v-for="opt in f.enum" :key="opt" :label="opt" :value="opt" />
      </el-select>

      <!-- integer / number -> input-number -->
      <el-input-number
        v-else-if="f.kind === 'number'"
        :model-value="value(f.key) as number"
        :min="f.min"
        :max="f.max"
        :step="f.step"
        size="small"
        controls-position="right"
        style="width: 100%"
        @update:model-value="set(f.key, $event)"
      />

      <!-- boolean -> switch -->
      <el-switch
        v-else-if="f.kind === 'boolean'"
        :model-value="value(f.key) as boolean"
        @update:model-value="set(f.key, $event)"
      />

      <!-- string[] -> free tags -->
      <el-select
        v-else-if="f.kind === 'array'"
        :model-value="(value(f.key) as string[]) ?? []"
        multiple
        filterable
        allow-create
        default-first-option
        size="small"
        placeholder="输入后回车添加"
        style="width: 100%"
        @update:model-value="set(f.key, $event)"
      />

      <!-- object{string:number} -> key/value rows (e.g. fusion weights) -->
      <div v-else-if="f.kind === 'map'" class="param-form__map">
        <div v-for="(row, i) in mapRows(f.key)" :key="i" class="param-form__map-row">
          <el-input :model-value="row.k" size="small" placeholder="source" @update:model-value="setMapKey(f.key, i, $event)" />
          <el-input-number :model-value="row.v" size="small" :step="0.1" controls-position="right" @update:model-value="setMapVal(f.key, i, $event)" />
          <el-button size="small" text @click="removeMapRow(f.key, i)">✕</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addMapRow(f.key)">+ 添加权重</el-button>
      </div>

      <!-- string -> input -->
      <el-input
        v-else
        :model-value="value(f.key) as string"
        size="small"
        @update:model-value="set(f.key, $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { ParamProperty, ParamSchema } from '@/types/operator'

const props = defineProps<{
  schemaJson: string
  modelValue: Record<string, unknown>
}>()
const emit = defineEmits<{ 'update:modelValue': [Record<string, unknown>] }>()

interface Field {
  key: string
  title: string
  kind: 'enum' | 'number' | 'boolean' | 'array' | 'map' | 'string'
  enum?: string[]
  min?: number
  max?: number
  step?: number
  default?: unknown
}

const schema = computed<ParamSchema>(() => {
  try { return JSON.parse(props.schemaJson || '{}') } catch { return {} }
})

const fields = computed<Field[]>(() => {
  const props_ = schema.value.properties ?? {}
  return Object.entries(props_).map(([key, p]) => toField(key, p))
})

function toField(key: string, p: ParamProperty): Field {
  const title = p.title || key
  if (p.enum) return { key, title, kind: 'enum', enum: p.enum, default: p.default }
  if (p.type === 'integer' || p.type === 'number') {
    return { key, title, kind: 'number', min: p.minimum, max: p.maximum, step: p.type === 'integer' ? 1 : 0.1, default: p.default }
  }
  if (p.type === 'boolean') return { key, title, kind: 'boolean', default: p.default }
  if (p.type === 'array') return { key, title, kind: 'array', default: p.default }
  if (p.type === 'object') return { key, title, kind: 'map', default: p.default }
  return { key, title, kind: 'string', default: p.default }
}

function value(key: string): unknown {
  const v = props.modelValue?.[key]
  if (v !== undefined) return v
  return fields.value.find(f => f.key === key)?.default
}

function set(key: string, val: unknown) {
  const next = { ...props.modelValue }
  // Clearing a field (e.g. emptying a number input emits null) reverts to the schema default
  // instead of writing null — null fails backend JSON-Schema (integer/number) on publish.
  if (val === null || val === undefined) delete next[key]
  else next[key] = val
  emit('update:modelValue', next)
}

// ---- map (weights) helpers ----
// Row list is the source of truth (so a half-typed / duplicate / empty key never drops a row
// mid-edit); only the valid subset is emitted into params. ParamForm is remounted per node
// (parent passes :key), so this local state starts fresh for each selected node.
const mapState = reactive<Record<string, { k: string; v: number }[]>>({})

function mapRows(key: string): { k: string; v: number }[] {
  if (!mapState[key]) {
    const obj = (props.modelValue?.[key] as Record<string, number>) ?? {}
    mapState[key] = Object.entries(obj).map(([k, v]) => ({ k, v }))
  }
  return mapState[key]
}
function emitMap(key: string) {
  const obj: Record<string, number> = {}
  for (const r of mapState[key]) if (r.k) obj[r.k] = r.v
  set(key, obj)
}
function setMapKey(key: string, i: number, k: string) { mapRows(key)[i].k = k; emitMap(key) }
function setMapVal(key: string, i: number, v: number) { mapRows(key)[i].v = v ?? 0; emitMap(key) }
function addMapRow(key: string) { mapRows(key).push({ k: '', v: 1.0 }); emitMap(key) }
function removeMapRow(key: string, i: number) { mapRows(key).splice(i, 1); emitMap(key) }
</script>

<style scoped>
.param-form { display: flex; flex-direction: column; gap: 14px; }
.param-form__empty { color: var(--kb-text-tertiary); font-size: 13px; padding: 8px 0; }
.param-form__field { display: flex; flex-direction: column; gap: 6px; }
.param-form__label { font-size: 12px; font-weight: 600; color: var(--kb-text-secondary); }
.param-form__map { display: flex; flex-direction: column; gap: 6px; }
.param-form__map-row { display: grid; grid-template-columns: 1fr 110px 28px; gap: 6px; align-items: center; }
</style>
