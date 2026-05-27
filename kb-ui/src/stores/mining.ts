import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MiningRun, MiningRunStage, MiningRunDocument } from '@/types'
import { useMiningApi } from '@/api/mining'
import { useDomainStore } from '@/stores/domain'

export const useMiningStore = defineStore('mining', () => {
  const runs = ref<MiningRun[]>([])
  const currentRun = ref<MiningRun | null>(null)
  const stages = ref<MiningRunStage[]>([])
  const documents = ref<MiningRunDocument[]>([])
  const progress = ref<{
    total: number; completed: number; failed: number; skipped: number
    processing: number; progress_percent: number; current_stage: string | null
    stage_summary: Record<string, { done: number; failed: number }>
  } | null>(null)
  const currentDocument = ref<MiningRunDocument | null>(null)
  const documentStages = ref<MiningRunStage[]>([])
  const documentArtifacts = ref<{
    run_id: string; document_id: string; snapshot_id: string | null
    segment_count: number; unit_count: number; relation_count: number
  } | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const miningApi = useMiningApi()
  const domainStore = useDomainStore()

  async function fetchRuns() {
    loading.value = true
    error.value = null
    try {
      runs.value = await miningApi.getRuns()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch runs'
    } finally {
      loading.value = false
    }
  }

  async function fetchRunDetail(runId: string) {
    loading.value = true
    error.value = null
    try {
      const [run, runStages, runDocsResult] = await Promise.all([
        miningApi.getRun(runId),
        miningApi.getRunStages(runId),
        miningApi.getRunDocuments(runId),
      ])
      currentRun.value = run
      stages.value = runStages
      documents.value = runDocsResult.documents
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch run detail'
    } finally {
      loading.value = false
    }
  }

  async function createRun(config: Record<string, unknown>) {
    try {
      await miningApi.createRun(config)
      await fetchRuns()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to create run'
      throw e
    }
  }

  async function cancelRun(runId: string) {
    try {
      await miningApi.cancelRun(runId)
      const run = runs.value.find(r => r.id === runId)
      if (run) run.status = 'cancelled'
      if (currentRun.value?.id === runId) currentRun.value.status = 'cancelled'
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to cancel run'
    }
  }

  async function publishRun(runId: string) {
    try {
      await miningApi.publishRun(runId, domainStore.currentDomain)
      const run = runs.value.find(r => r.id === runId)
      if (run) run.build_id = `bld_${runId}`
      if (currentRun.value?.id === runId) currentRun.value.build_id = `bld_${runId}`
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to publish run'
    }
  }

  async function fetchProgress(runId: string) {
    try {
      progress.value = await miningApi.getRunProgress(runId)
    } catch {
      // silently ignore progress fetch failures
    }
  }

  async function fetchDocumentDetail(runId: string, docId: string) {
    loading.value = true
    error.value = null
    try {
      const [doc, docStages, docArts] = await Promise.all([
        miningApi.getRunDocument(runId, docId),
        miningApi.getRunDocumentStages(runId, docId),
        miningApi.getRunDocumentArtifacts(runId, docId),
      ])
      currentDocument.value = doc
      documentStages.value = docStages
      documentArtifacts.value = docArts
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch document detail'
    } finally {
      loading.value = false
    }
  }

  function clearCurrentRun() {
    currentRun.value = null
    stages.value = []
    documents.value = []
    progress.value = null
    currentDocument.value = null
    documentStages.value = []
    documentArtifacts.value = null
  }

  return {
    runs, currentRun, stages, documents, progress,
    currentDocument, documentStages, documentArtifacts,
    loading, error,
    fetchRuns, fetchRunDetail, fetchProgress,
    fetchDocumentDetail,
    createRun, cancelRun, publishRun, clearCurrentRun,
  }
})
