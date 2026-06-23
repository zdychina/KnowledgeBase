import { createRouter, createWebHistory } from 'vue-router'
import { useDomainStore } from '@/stores/domain'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
        },
        {
          path: 'mining',
          name: 'mining',
          component: () => import('@/views/mining/RunsView.vue'),
        },
        {
          path: 'mining/create',
          name: 'mining-create',
          component: () => import('@/views/mining/CreateRunView.vue'),
        },
        {
          path: 'mining/:runId',
          name: 'mining-detail',
          component: () => import('@/views/mining/RunDetailView.vue'),
          props: true,
        },
        {
          path: 'mining/:runId/documents/:docId',
          name: 'mining-document-detail',
          component: () => import('@/views/mining/RunDocumentDetailView.vue'),
          props: true,
        },
        {
          path: 'search',
          name: 'search',
          component: () => import('@/views/SearchView.vue'),
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('@/views/knowledge/DocumentsView.vue'),
        },
        {
          path: 'knowledge/:docId',
          name: 'knowledge-detail',
          component: () => import('@/views/knowledge/DocumentDetailView.vue'),
          props: true,
        },
        {
          path: 'graph',
          name: 'graph',
          component: () => import('@/views/knowledge/GraphView.vue'),
        },
        {
          path: 'llm',
          name: 'llm',
          component: () => import('@/views/LlmView.vue'),
        },
        {
          path: 'llm/:taskId',
          name: 'llm-task-detail',
          component: () => import('@/views/llm/LlmTaskDetailView.vue'),
          props: true,
        },
        {
          path: 'paradigm',
          name: 'paradigm',
          component: () => import('@/views/paradigm/ParadigmListView.vue'),
        },
        {
          path: 'paradigm/:id',
          name: 'paradigm-edit',
          component: () => import('@/views/paradigm/ParadigmEditorView.vue'),
          props: true,
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
        },
      ],
    },
  ],
})

// Load domain list from main_control_service before first navigation
let domainsInitialized = false
router.beforeEach(async () => {
  if (!domainsInitialized) {
    domainsInitialized = true
    const domainStore = useDomainStore()
    await domainStore.fetchDomains()
  }
})

export default router
