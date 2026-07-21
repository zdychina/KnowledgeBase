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

describe('mining store queued submission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('inserts the accepted queued run immediately and returns its id', async () => {
    const domain = useDomainStore()
    domain.currentDomain = 'odn'
    api.createRun.mockResolvedValue({
      run_id: 'run-new', status: 'queued', current_stage: 'queued',
      started_at: '2026-07-20T00:00:00Z',
    })
    const store = useMiningStore()

    const run = await store.createRun({ domain: 'odn', input_path: 'C:/incoming' })

    expect(run.id).toBe('run-new')
    expect(store.runs[0]).toMatchObject({
      id: 'run-new', status: 'queued', current_stage: 'queued', domain: 'odn',
    })
    expect(api.getRuns).not.toHaveBeenCalled()
  })

  it('drops a create response after the selected domain changes', async () => {
    let resolveCreate!: (value: unknown) => void
    api.createRun.mockReturnValue(new Promise(resolve => { resolveCreate = resolve }))
    const domain = useDomainStore()
    domain.currentDomain = 'odn'
    const store = useMiningStore()
    const pending = store.createRun({ domain: 'odn', input_path: 'C:/incoming' })

    domain.currentDomain = 'civil_engineering'
    resolveCreate({ run_id: 'stale', status: 'queued', current_stage: 'queued', started_at: '' })
    await pending

    expect(store.runs).toEqual([])
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
