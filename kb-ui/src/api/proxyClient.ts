import axios from 'axios'
import { useDomainStore } from '@/stores/domain'

/**
 * Create an axios client that routes requests through the main_control_service
 * reverse proxy. The baseURL is resolved on every request via an interceptor,
 * so domain switching is reflected immediately.
 */
export function createProxyClient(service: string) {
  const client = axios.create()
  client.interceptors.request.use((config) => {
    const domain = useDomainStore()
    config.baseURL = `/api/control-plane/api/v1/proxy/${domain.currentDomain}/${service}`
    // Mining read endpoints filter by domain via the `domain` query param.
    // Default to the active domain unless the caller explicitly supplies one.
    if (service === 'mining') {
      config.params = { ...config.params, domain: config.params?.domain ?? domain.currentDomain }
    }
    return config
  })
  return client
}

/**
 * Normalize API response items — handles {items}, {data}, and bare arrays.
 */
export function extractItems<T>(data: unknown, extraKeys: string[] = []): T[] {
  if (Array.isArray(data)) return data
  const obj = data as Record<string, unknown>
  for (const key of ['items', 'data', ...extraKeys]) {
    const val = obj[key]
    if (Array.isArray(val)) return val
  }
  return []
}

/**
 * Unwrap {data: ...} envelope from API response.
 */
export function extractOne<T>(data: unknown): T {
  const obj = data as Record<string, unknown>
  return (obj.data ?? obj) as T
}
