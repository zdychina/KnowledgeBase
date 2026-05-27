<template>
  <div class="stats-card">
    <div class="stats-card__icon">{{ icon }}</div>
    <div class="stats-card__body">
      <div class="stats-card__label">{{ label }}</div>
      <div class="stats-card__value">{{ value }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  value: string | number
  sub?: string
  icon?: string
}>(), {
  icon: '',
})
</script>

<style scoped>
.stats-card {
  background: var(--kb-bg-card);
  border-radius: var(--kb-radius);
  padding: 16px 18px;
  border: 1px solid var(--kb-border-light);
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all var(--kb-duration) var(--kb-ease);
}

.stats-card:hover {
  border-color: var(--kb-accent-medium);
  box-shadow: 0 2px 8px rgba(8, 145, 178, 0.08);
}

.stats-card__icon {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.stats-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.stats-card__label {
  font-size: 11px;
  color: var(--kb-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 600;
}

.stats-card__value {
  font-size: 24px;
  font-weight: 700;
  color: var(--kb-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
  line-height: 1.15;
}
</style>
