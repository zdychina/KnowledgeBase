import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

const state = vi.hoisted(() => ({
  domain: { currentDomain: 'odn' },
  store: {
    runs: [{ id: 'r1', status: 'queued', current_stage: 'queued', total_documents: 0,
      committed_count: 0, failed_count: 0, skipped_count: 0, new_count: 0, updated_count: 0 }],
    loading: false,
    error: null as string | null,
    fetchRuns: vi.fn(async () => undefined),
    cancelRun: vi.fn(), publishRun: vi.fn(), createRun: vi.fn(),
  },
}))

vi.mock('@/stores/domain', () => ({ useDomainStore: () => state.domain }))
vi.mock('@/stores/mining', () => ({ useMiningStore: () => state.store }))
vi.mock('@/api/mining', () => ({ useMiningApi: () => ({ uploadFiles: vi.fn() }) }))

import RunsView from '../RunsView.vue'

describe('RunsView active run polling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    state.store.fetchRuns.mockClear()
    state.store.runs[0].status = 'queued'
  })
  afterEach(() => vi.useRealTimers())

  it('polls queued runs every three seconds and stops after terminal state', async () => {
    const wrapper = shallowMount(RunsView, {
      global: { stubs: { ElTableColumn: true } },
    })
    await flushPromises()
    expect(state.store.fetchRuns).toHaveBeenCalled()
    const initialCalls = state.store.fetchRuns.mock.calls.length

    await vi.advanceTimersByTimeAsync(3000)
    expect(state.store.fetchRuns.mock.calls.length).toBe(initialCalls + 1)
    expect(state.store.fetchRuns).toHaveBeenLastCalledWith({ silent: true })

    state.store.runs[0].status = 'completed'
    await vi.advanceTimersByTimeAsync(6000)
    expect(state.store.fetchRuns.mock.calls.length).toBe(initialCalls + 1)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(6000)
    expect(state.store.fetchRuns.mock.calls.length).toBe(initialCalls + 1)
  })
})
