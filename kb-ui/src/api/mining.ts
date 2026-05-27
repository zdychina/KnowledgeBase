import axios from 'axios'
import type {
  MiningRun, MiningRunStage, MiningRunDocument, KnowledgeStats, HealthStatus,
  KnowledgeDocument, KnowledgeSegment, KnowledgeUnit, KnowledgeRelation,
  UploadConfig, UploadResult,
} from '@/types'
import type { PaginatedResponse } from '@/types'
import { useDomainStore } from '@/stores/domain'

function extractItems<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data
  const obj = data as Record<string, unknown>
  const items = obj.items ?? obj.data ?? obj.stages
  if (Array.isArray(items)) return items
  return []
}

function extractOne<T>(data: unknown): T {
  const obj = data as Record<string, unknown>
  return (obj.data ?? obj) as T
}

export function useMiningApi() {
  const domain = useDomainStore()
  const client = axios.create({ baseURL: domain.currentConfig.miningApi })

  return {
    // Health
    async getHealth(): Promise<HealthStatus> {
      const { data } = await client.get('/health')
      return data
    },

    // Stats
    async getStats(): Promise<KnowledgeStats> {
      const { data } = await client.get('/api/knowledge/stats')
      return data
    },

    // Runs
    async getRuns(params?: { status?: string; limit?: number }): Promise<MiningRun[]> {
      const { data } = await client.get('/api/runs', { params })
      return extractItems<MiningRun>(data)
    },

    async getRun(runId: string): Promise<MiningRun> {
      const { data } = await client.get(`/api/runs/${runId}`)
      return extractOne<MiningRun>(data)
    },

    async getRunStages(runId: string): Promise<MiningRunStage[]> {
      const { data } = await client.get(`/api/runs/${runId}/stages`)
      return extractItems<MiningRunStage>(data)
    },

    async getRunDocuments(runId: string, params?: {
      status?: string; action?: string; has_error?: boolean; page?: number; page_size?: number
    }): Promise<{ total: number; page: number; page_size: number; documents: MiningRunDocument[] }> {
      const { data } = await client.get(`/api/runs/${runId}/documents`, { params })
      return data
    },

    async getRunProgress(runId: string): Promise<{
      run_id: string; total: number; completed: number; failed: number
      skipped: number; processing: number; progress_percent: number
      current_stage: string | null; stage_summary: Record<string, { done: number; failed: number }>
    }> {
      const { data } = await client.get(`/api/runs/${runId}/progress`)
      return data
    },

    async createRun(config: Record<string, unknown>): Promise<MiningRun> {
      const { data } = await client.post('/api/runs', config)
      return extractOne<MiningRun>(data)
    },

    async cancelRun(runId: string): Promise<void> {
      await client.post(`/api/runs/${runId}/cancel`)
    },

    async publishRun(runId: string, domain?: string): Promise<void> {
      await client.post(`/api/runs/${runId}/publish`, domain ? { domain } : undefined)
    },

    // Run document detail
    async getRunDocument(runId: string, docId: string): Promise<MiningRunDocument> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}`)
      return data
    },

    async getRunDocumentStages(runId: string, docId: string): Promise<MiningRunStage[]> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}/stages`)
      return extractItems<MiningRunStage>(data)
    },

    async getRunDocumentArtifacts(runId: string, docId: string): Promise<{
      run_id: string; document_id: string; snapshot_id: string | null
      segment_count: number; unit_count: number; relation_count: number
    }> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}/artifacts`)
      return data
    },

    async getRunDocumentSegments(runId: string, docId: string, params?: {
      limit?: number; offset?: number
    }): Promise<{ run_id: string; document_id: string; snapshot_id: string | null; items: KnowledgeSegment[] }> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}/segments`, { params })
      return data
    },

    async getRunDocumentUnits(runId: string, docId: string, params?: {
      unit_type?: string; limit?: number; offset?: number
    }): Promise<{ run_id: string; document_id: string; snapshot_id: string | null; items: KnowledgeUnit[] }> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}/units`, { params })
      return data
    },

    async getRunDocumentRelations(runId: string, docId: string, params?: {
      limit?: number; offset?: number
    }): Promise<{ run_id: string; document_id: string; snapshot_id: string | null; items: KnowledgeRelation[] }> {
      const { data } = await client.get(`/api/runs/${runId}/documents/${docId}/relations`, { params })
      return data
    },

    async getRunArtifacts(runId: string): Promise<{
      run_id: string; document_count: number
      segment_count: number; unit_count: number; relation_count: number
    }> {
      const { data } = await client.get(`/api/runs/${runId}/artifacts`)
      return data
    },

    // Upload
    async getUploadConfig(): Promise<UploadConfig> {
      const { data } = await client.get('/api/uploads/config')
      return data
    },

    async uploadFiles(
      domain: string,
      files: File[],
      onUploadProgress?: (progressEvent: { loaded: number; total: number; progress: number }) => void,
    ): Promise<UploadResult> {
      const form = new FormData()
      form.append('domain', domain)
      for (const f of files) {
        form.append('files', f)
      }
      const { data } = await client.post('/api/uploads', form, {
        onUploadProgress(e) {
          if (onUploadProgress && e.total) {
            onUploadProgress({ loaded: e.loaded, total: e.total, progress: Math.round((e.loaded / e.total) * 100) })
          }
        },
      })
      return data
    },

    async listUploads(domain?: string): Promise<{
      items: Array<{
        upload_batch_id: string
        domain: string
        file_count: number
        files: string[]
        storage_path: string
      }>
    }> {
      const { data } = await client.get('/api/uploads', { params: domain ? { domain } : undefined })
      return data
    },

    // Knowledge assets
    async getDocuments(params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<KnowledgeDocument>> {
      const { data } = await client.get('/api/knowledge/documents', { params })
      return data
    },

    async getDocument(docId: string): Promise<KnowledgeDocument> {
      const { data } = await client.get(`/api/knowledge/documents/${docId}`)
      return extractOne<KnowledgeDocument>(data)
    },

    async getDocumentSegments(docId: string): Promise<KnowledgeSegment[]> {
      const { data } = await client.get(`/api/knowledge/documents/${docId}/segments`)
      return extractItems<KnowledgeSegment>(data)
    },

    async getDocumentUnits(docId: string): Promise<KnowledgeUnit[]> {
      const { data } = await client.get(`/api/knowledge/documents/${docId}/units`)
      return extractItems<KnowledgeUnit>(data)
    },

    async getDocumentRelations(docId: string): Promise<KnowledgeRelation[]> {
      try {
        const { data } = await client.get(`/api/knowledge/documents/${docId}/relations`)
        return extractItems<KnowledgeRelation>(data)
      } catch {
        return []
      }
    },

    async getSegments(params?: { limit?: number }): Promise<PaginatedResponse<KnowledgeSegment>> {
      const { data } = await client.get('/api/knowledge/segments', { params })
      return data
    },

    async getUnits(params?: { limit?: number }): Promise<PaginatedResponse<KnowledgeUnit>> {
      const { data } = await client.get('/api/knowledge/units', { params })
      return data
    },

    async getRelations(params?: { limit?: number }): Promise<PaginatedResponse<KnowledgeRelation>> {
      const { data } = await client.get('/api/knowledge/relations', { params })
      return data
    },
  }
}
