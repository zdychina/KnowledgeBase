import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { DomainConfig, DomainMap } from '@/types'

const STORAGE_KEY = 'kb-ui-domains'

const DEFAULT_DOMAINS: DomainMap = {
  cloud_core_network: {
    miningApi: '/api/mining',
    servingApi: '/api/serving',
    llmApi: '/api/llm',
    active: true,
  },
  ip_network: {
    miningApi: '/api/mining',
    servingApi: '/api/serving',
    llmApi: '/api/llm',
    active: true,
  },
  generic: {
    miningApi: '/api/mining',
    servingApi: '/api/serving',
    llmApi: '/api/llm',
    active: false,
  },
}

function loadDomains(): DomainMap {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return { ...DEFAULT_DOMAINS }
}

export const useDomainStore = defineStore('domain', () => {
  const domains = ref<DomainMap>(loadDomains())
  const currentDomain = ref<string>(
    Object.keys(domains.value).find(k => domains.value[k].active) || Object.keys(domains.value)[0]
  )

  const currentConfig = computed<DomainConfig>(() => domains.value[currentDomain.value])
  const activeDomains = computed(() =>
    Object.entries(domains.value)
      .filter(([, cfg]) => cfg.active)
      .map(([name]) => name)
  )

  function switchDomain(domain: string) {
    if (domains.value[domain]) {
      currentDomain.value = domain
    }
  }

  function updateDomain(name: string, config: DomainConfig) {
    domains.value = { ...domains.value, [name]: config }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(domains.value))
  }

  function addDomain(name: string, config: DomainConfig) {
    domains.value = { ...domains.value, [name]: config }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(domains.value))
  }

  function removeDomain(name: string) {
    const updated = { ...domains.value }
    delete updated[name]
    domains.value = updated
    if (currentDomain.value === name) {
      currentDomain.value = Object.keys(updated)[0] || ''
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(domains.value))
  }

  return {
    domains,
    currentDomain,
    currentConfig,
    activeDomains,
    switchDomain,
    updateDomain,
    addDomain,
    removeDomain,
  }
})
