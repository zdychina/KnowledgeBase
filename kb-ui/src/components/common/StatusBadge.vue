<template>
  <span class="status-badge" :class="[`status-badge--${status}`, sizeClass]">
    <span class="status-badge__dot" />
    <span class="status-badge__text"><slot /></span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  status: 'completed' | 'running' | 'failed' | 'cancelled' | 'pending' | 'queued' | 'succeeded' | 'dead_letter' | 'committed' | 'processing' | 'skipped'
  size?: 'small' | 'default'
}>(), {
  size: 'default',
})

const sizeClass = computed(() => `status-badge--${props.size}`)
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 12px;
  border-radius: 12px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.status-badge--small {
  padding: 1px 8px;
  font-size: 11px;
}

.status-badge--default {
  font-size: 12px;
}

.status-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Status colors */
.status-badge--completed,
.status-badge--succeeded,
.status-badge--committed {
  background: var(--kb-success-soft);
  color: var(--kb-success);
}
.status-badge--completed .status-badge__dot,
.status-badge--succeeded .status-badge__dot,
.status-badge--committed .status-badge__dot {
  background: var(--kb-success);
}

.status-badge--running,
.status-badge--queued {
  background: var(--kb-warning-soft);
  color: var(--kb-warning);
}
.status-badge--running .status-badge__dot,
.status-badge--queued .status-badge__dot {
  background: var(--kb-warning);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.status-badge--failed,
.status-badge--dead_letter {
  background: var(--kb-danger-soft);
  color: var(--kb-danger);
}
.status-badge--failed .status-badge__dot,
.status-badge--dead_letter .status-badge__dot {
  background: var(--kb-danger);
}

.status-badge--cancelled,
.status-badge--pending,
.status-badge--processing,
.status-badge--skipped {
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
}
.status-badge--cancelled .status-badge__dot,
.status-badge--pending .status-badge__dot,
.status-badge--processing .status-badge__dot,
.status-badge--skipped .status-badge__dot {
  background: var(--kb-accent);
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
