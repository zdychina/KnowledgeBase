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

describe('RunsView run loading', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    state.store.fetchRuns.mockClear()
    state.store.runs[0].status = 'queued'
  })
  afterEach(() => vi.useRealTimers())

  // v6 的 RunsView 仅在挂载与切域时拉取，不做定时轮询。
  it('fetches runs once on mount and does not poll on a timer', async () => {
    const wrapper = shallowMount(RunsView, {
      global: { stubs: { ElTableColumn: true } },
    })
    await flushPromises()
    expect(state.store.fetchRuns).toHaveBeenCalledTimes(1)

    // 即使存在运行中的作业，也不应随时间自动再次拉取
    state.store.runs[0].status = 'running'
    await vi.advanceTimersByTimeAsync(30000)
    expect(state.store.fetchRuns).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })
})
