<template>
  <div class="app-layout">
    <Sidebar />
    <div class="app-layout__main">
      <Header />
      <main class="app-layout__content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import Header from './Header.vue'
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: var(--kb-bg-page);
}

.app-layout__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  margin-left: var(--kb-sidebar-width);
  min-width: 0;
}

.app-layout__content {
  flex: 1;
  padding: 24px 28px;
  overflow-y: auto;
}
</style>
