import { describe, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  createRun: vi.fn(),
  getRuns: vi.fn(),
  getRun: vi.fn(),
  getRunStages: vi.fn(),
  getRunDocuments: vi.fn(),
}))

vi.mock('@/api/mining', () => ({ useMiningApi: () => api }))

import { useDomainStore } from '@/stores/domain'
import { useMiningStore } from '@/stores/mining'

describe('mining store run submission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  // v6 的 createRun 不做乐观插入，而是提交成功后重新拉取整个列表。
  it('creates a run via the API then refetches the list', async () => {
    const domain = useDomainStore()
    domain.currentDomain = 'odn'
    api.createRun.mockResolvedValue({ run_id: 'run-new', status: 'queued', current_stage: 'queued' })
    api.getRuns.mockResolvedValue([
      { id: 'run-new', status: 'queued', current_stage: 'queued', domain: 'odn' },
    ])
    const store = useMiningStore()

    await store.createRun({ domain: 'odn', input_path: 'C:/incoming' })

    expect(api.createRun).toHaveBeenCalledWith({ domain: 'odn', input_path: 'C:/incoming' })
    expect(api.getRuns).toHaveBeenCalledWith('odn')
    expect(store.runs[0].id).toBe('run-new')
  })

  it('surfaces and rethrows a create failure without refetching', async () => {
    const domain = useDomainStore()
    domain.currentDomain = 'odn'
    api.createRun.mockRejectedValue(new Error('backend down'))
    const store = useMiningStore()

    await expect(store.createRun({ domain: 'odn', input_path: 'C:/incoming' }))
      .rejects.toThrow('backend down')
    expect(store.error).toBe('backend down')
    // createRun 先失败，fetchRuns 不会被触及
    expect(api.getRuns).not.toHaveBeenCalled()
  })

  it('silent refresh preserves rows and exposes an error', async () => {
    const domain = useDomainStore()
    domain.currentDomain = 'odn'
    const store = useMiningStore()
    store.runs = [{ id: 'old', status: 'running' } as never]
    api.getRuns.mockRejectedValue(new Error('refresh failed'))

    await store.fetchRuns({ silent: true })

    expect(store.runs[0].id).toBe('old')
    expect(store.loading).toBe(false)
    expect(store.error).toBe('refresh failed')
  })
})
