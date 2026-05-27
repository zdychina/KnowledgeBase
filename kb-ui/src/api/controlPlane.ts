import axios from 'axios'
import type {
  ControlPlaneAuditLog,
  ControlPlaneCapability,
  ControlPlaneDatabaseBinding,
  ControlPlaneDiffItem,
  ControlPlaneDomainDetail,
  ControlPlaneDomainSummary,
  ControlPlaneObservationPayload,
  ControlPlaneRuntimeOverride,
  ControlPlaneRuntimePayload,
  ControlPlaneServiceBinding,
  ControlPlaneServiceInstance,
} from '@/types'

const baseURL = import.meta.env.VITE_CONTROL_PLANE_API_BASE || 'http://localhost:8910'
const client = axios.create({ baseURL })

export function useControlPlaneApi() {
  return {
    async getDomains(): Promise<ControlPlaneDomainSummary[]> {
      const { data } = await client.get('/api/domains')
      return data.items ?? []
    },

    async getDomain(domainId: string): Promise<ControlPlaneDomainDetail> {
      const { data } = await client.get(`/api/domains/${domainId}`)
      return data
    },

    async getRuntime(domainId: string): Promise<ControlPlaneRuntimePayload> {
      const { data } = await client.get(`/api/domains/${domainId}/runtime`)
      return data
    },

    async getObservations(domainId: string): Promise<ControlPlaneObservationPayload> {
      const { data } = await client.get(`/api/domains/${domainId}/observations`)
      return data
    },

    async getDiff(domainId: string): Promise<{ domain: string; items: ControlPlaneDiffItem[] }> {
      const { data } = await client.get(`/api/domains/${domainId}/diff`)
      return data
    },

    async bootstrapImport(): Promise<{ imported_domains: number; service_instances: number }> {
      const { data } = await client.post('/api/bootstrap/import-current-state')
      return data
    },

    async listServiceInstances(): Promise<ControlPlaneServiceInstance[]> {
      const { data } = await client.get('/api/service-instances')
      return data.items ?? []
    },

    async patchDomain(domainId: string, payload: Partial<ControlPlaneDomainDetail>): Promise<ControlPlaneDomainDetail> {
      const { data } = await client.patch(`/api/domains/${domainId}`, payload)
      return data
    },

    async replaceCapabilities(domainId: string, capabilities: ControlPlaneCapability[]): Promise<ControlPlaneCapability[]> {
      const { data } = await client.put(`/api/domains/${domainId}/capabilities`, { capabilities })
      return data.items ?? []
    },

    async replaceServiceBindings(domainId: string, bindings: ControlPlaneServiceBinding[]): Promise<ControlPlaneServiceBinding[]> {
      const { data } = await client.put(`/api/domains/${domainId}/service-bindings`, { bindings })
      return data.items ?? []
    },

    async replaceDatabaseBindings(domainId: string, bindings: ControlPlaneDatabaseBinding[]): Promise<ControlPlaneDatabaseBinding[]> {
      const { data } = await client.put(`/api/domains/${domainId}/database-bindings`, { bindings })
      return data.items ?? []
    },

    async replaceOverrides(domainId: string, overrides: ControlPlaneRuntimeOverride[]): Promise<ControlPlaneRuntimeOverride[]> {
      const payload = {
        overrides: overrides.map(item => ({
          service_name: item.service_name,
          config_scope: item.config_scope,
          config_json: item.config_json,
          version_tag: item.version_tag,
        })),
      }
      const { data } = await client.put(`/api/domains/${domainId}/overrides`, payload)
      return data.items ?? []
    },

    async listAuditLogs(): Promise<ControlPlaneAuditLog[]> {
      const { data } = await client.get('/api/audit-logs')
      return data.items ?? []
    },
  }
}

