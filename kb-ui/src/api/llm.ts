import axios from 'axios'
import type { HealthStatus, LlmTaskStats, LlmTask, LlmTaskDetail } from '@/types'
import { useDomainStore } from '@/stores/domain'

function extractItems<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data
  const obj = data as Record<string, unknown>
  const items = obj.items ?? obj.data
  if (Array.isArray(items)) return items
  return []
}

export function useLlmApi() {
  const domain = useDomainStore()
  const client = axios.create({ baseURL: domain.currentConfig.llmApi })

  return {
    async getHealth(): Promise<HealthStatus> {
      const { data } = await client.get('/health')
      return data
    },

    async getStats(params?: { domain?: string; service?: string }): Promise<LlmTaskStats> {
      const { data } = await client.get('/api/v1/stats', { params })
      // API returns { success: true, data: { ... } }
      const resp = data as Record<string, unknown>
      return (resp.data ?? resp) as LlmTaskStats
    },

    /**
     * GET /api/v1/tasks — returns { success, data: { total, page, page_size, items } }
     */
    async getTasks(params?: {
      status?: string
      task_type?: string
      domain?: string
      service?: string
      stage?: string
      page?: number
      page_size?: number
    }): Promise<{ total: number; items: LlmTask[] }> {
      const { data } = await client.get('/api/v1/tasks', { params })
      const resp = data as Record<string, unknown>
      const d = (resp.data ?? resp) as Record<string, unknown>
      return {
        total: (d.total as number) ?? 0,
        items: extractItems<LlmTask>(d),
      }
    },

    async getTask(taskId: string): Promise<LlmTaskDetail> {
      const { data } = await client.get(`/api/v1/tasks/${taskId}`)
      const obj = data as Record<string, unknown>
      return (obj.data ?? obj) as LlmTaskDetail
    },

    async getTaskRequest(taskId: string): Promise<Record<string, unknown> | null> {
      try {
        const { data } = await client.get(`/api/v1/tasks/${taskId}/request`)
        const resp = data as Record<string, unknown>
        return (resp.data ?? resp) as Record<string, unknown>
      } catch { return null }
    },

    async getTaskResult(taskId: string): Promise<Record<string, unknown> | null> {
      try {
        const { data } = await client.get(`/api/v1/tasks/${taskId}/result`)
        const resp = data as Record<string, unknown>
        return (resp.data ?? resp) as Record<string, unknown>
      } catch { return null }
    },

    async getTaskAttempts(taskId: string): Promise<Record<string, unknown>[]> {
      try {
        const { data } = await client.get(`/api/v1/tasks/${taskId}/attempts`)
        const resp = data as Record<string, unknown>
        return extractItems<Record<string, unknown>>(resp.data ?? resp)
      } catch { return [] }
    },

    async getTaskEvents(taskId: string): Promise<Record<string, unknown>[]> {
      try {
        const { data } = await client.get(`/api/v1/tasks/${taskId}/events`)
        const resp = data as Record<string, unknown>
        return extractItems<Record<string, unknown>>(resp.data ?? resp)
      } catch { return [] }
    },

    async cancelTask(taskId: string): Promise<void> {
      await client.post(`/api/v1/tasks/${taskId}/cancel`)
    },

    async getTemplates(params?: { domain?: string }): Promise<Record<string, unknown>[]> {
      try {
        const { data } = await client.get('/api/v1/templates', { params })
        return Array.isArray(data) ? data : []
      } catch { return [] }
    },
  }
}
