<template>
  <div class="expandable-text">
    <span
      class="expandable-text__body"
      :class="{ 'is-clamped': !expanded && clamped }"
      >{{ text }}</span
    >
    <button
      v-if="toggleable"
      type="button"
      class="expandable-text__toggle"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : '展开' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    /** 折叠时显示的最大行数 */
    maxLines?: number
    /** 折叠时显示的最大字符数；超过此长度才显示「展开」按钮 */
    maxLength?: number
  }>(),
  {
    maxLines: 3,
    maxLength: 120,
  },
)

const expanded = ref(false)

// 仅当文本足够长时才允许展开/收起，避免短文本还挂个按钮
const toggleable = computed(() => (props.text?.length ?? 0) > props.maxLength)
// 未展开时是否应用 line-clamp（只要可切换就折叠显示，否则原样）
const clamped = computed(() => toggleable.value)
</script>

<style scoped>
.expandable-text {
  font-size: 12px;
  color: var(--kb-text-secondary);
  line-height: 1.5;
  word-break: break-all;
}
.expandable-text__body {
  white-space: pre-wrap;
  word-break: break-all;
}
.expandable-text__body.is-clamped {
  display: -webkit-box;
  -webkit-line-clamp: v-bind('props.maxLines');
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.expandable-text__toggle {
  margin-top: 2px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  color: var(--kb-accent);
  line-height: 1;
}
.expandable-text__toggle:hover {
  text-decoration: underline;
}
</style>
