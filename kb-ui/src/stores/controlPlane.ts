import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useControlPlaneApi } from '@/api/controlPlane'
import { useDomainStore } from '@/stores/domain'
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

export const useControlPlaneStore = defineStore('control-plane', () => {
  const api = useControlPlaneApi()
  const legacyDomainStore = useDomainStore()

  const domains = ref<ControlPlaneDomainSummary[]>([])
  const selectedDomainId = ref<string>('')
  const selectedDomain = ref<ControlPlaneDomainDetail | null>(null)
  const runtime = ref<ControlPlaneRuntimePayload | null>(null)
  const observations = ref<ControlPlaneObservationPayload | null>(null)
  const diffItems = ref<ControlPlaneDiffItem[]>([])
  const serviceInstances = ref<ControlPlaneServiceInstance[]>([])
  const auditLogs = ref<ControlPlaneAuditLog[]>([])
  const loading = ref(false)
  const bootstrapping = ref(false)
  const error = ref<string>('')

  const selectedSummary = computed(() =>
    domains.value.find(item => item.domain_id === selectedDomainId.value) || null
  )

  async function loadDomains() {
    loading.value = true
    error.value = ''
    try {
      domains.value = await api.getDomains()
      serviceInstances.value = await api.listServiceInstances()
      if (!selectedDomainId.value) {
        const preferred = domains.value.find(item => item.domain_id === legacyDomainStore.currentDomain)
        selectedDomainId.value = preferred?.domain_id || domains.value[0]?.domain_id || ''
      }
      if (selectedDomainId.value) {
        await loadDomain(selectedDomainId.value)
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load control plane'
    } finally {
      loading.value = false
    }
  }

  async function loadDomain(domainId: string) {
    if (!domainId) return
    loading.value = true
    error.value = ''
    selectedDomainId.value = domainId
    try {
      const [domain, runtimeData, observationData, diffData, audits] = await Promise.all([
        api.getDomain(domainId),
        api.getRuntime(domainId),
        api.getObservations(domainId),
        api.getDiff(domainId),
        api.listAuditLogs(),
      ])
      selectedDomain.value = domain
      runtime.value = runtimeData
      observations.value = observationData
      diffItems.value = diffData.items
      auditLogs.value = audits
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load control-plane detail'
    } finally {
      loading.value = false
    }
  }

  async function bootstrapImport() {
    bootstrapping.value = true
    error.value = ''
    try {
      await api.bootstrapImport()
      await loadDomains()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to bootstrap control plane'
      throw err
    } finally {
      bootstrapping.value = false
    }
  }

  async function saveDomainPatch(payload: Partial<ControlPlaneDomainDetail>) {
    if (!selectedDomainId.value) return
    await api.patchDomain(selectedDomainId.value, payload)
    await loadDomain(selectedDomainId.value)
  }

  async function saveCapabilities(capabilities: ControlPlaneCapability[]) {
    if (!selectedDomainId.value) return
    await api.replaceCapabilities(selectedDomainId.value, capabilities)
    await loadDomain(selectedDomainId.value)
  }

  async function saveServiceBindings(bindings: ControlPlaneServiceBinding[]) {
    if (!selectedDomainId.value) return
    await api.replaceServiceBindings(selectedDomainId.value, bindings)
    await loadDomain(selectedDomainId.value)
  }

  async function saveDatabaseBindings(bindings: ControlPlaneDatabaseBinding[]) {
    if (!selectedDomainId.value) return
    await api.replaceDatabaseBindings(selectedDomainId.value, bindings)
    await loadDomain(selectedDomainId.value)
  }

  async function saveOverrides(overrides: ControlPlaneRuntimeOverride[]) {
    if (!selectedDomainId.value) return
    await api.replaceOverrides(selectedDomainId.value, overrides)
    await loadDomain(selectedDomainId.value)
  }

  return {
    domains,
    selectedDomainId,
    selectedDomain,
    selectedSummary,
    runtime,
    observations,
    diffItems,
    serviceInstances,
    auditLogs,
    loading,
    bootstrapping,
    error,
    loadDomains,
    loadDomain,
    bootstrapImport,
    saveDomainPatch,
    saveCapabilities,
    saveServiceBindings,
    saveDatabaseBindings,
    saveOverrides,
  }
})
