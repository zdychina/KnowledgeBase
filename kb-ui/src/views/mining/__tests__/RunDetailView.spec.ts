import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

const state = vi.hoisted(() => ({
  domain: { currentDomain: 'odn' },
  store: {
    currentRun: { id: 'r1', status: 'queued', current_stage: 'queued', total_documents: 0,
      committed_count: 0, failed_count: 0, skipped_count: 0, new_count: 0, updated_count: 0 },
    stages: [], documents: [], documentsTotal: 0, documentsPage: 1,
    progress: { total: 0, completed: 0, failed: 0, skipped: 0, processing: 0,
      progress_percent: 0, current_stage: null, run_stage: 'ingest', stage_summary: {} },
    error: null,
    fetchRunDetail: vi.fn(async () => undefined),
    fetchProgress: vi.fn(async () => undefined),
    fetchRunDocuments: vi.fn(), clearCurrentRun: vi.fn(), cancelRun: vi.fn(),
  },
}))

const api = vi.hoisted(() => ({
  getRunTrace: vi.fn().mockRejectedValue(new Error('no trace')),
  resumeRun: vi.fn(),
}))

vi.mock('@/stores/domain', () => ({ useDomainStore: () => state.domain }))
vi.mock('@/stores/mining', () => ({ useMiningStore: () => state.store }))
vi.mock('@/api/mining', () => ({ useMiningApi: () => api }))

import RunDetailView from '../RunDetailView.vue'

describe('RunDetailView queued and ingest states', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    state.store.fetchRunDetail.mockClear()
    state.store.fetchProgress.mockClear()
    state.store.currentRun.status = 'queued'
    state.store.currentRun.current_stage = 'queued'
    api.resumeRun.mockReset()
  })
  afterEach(() => vi.useRealTimers())

  it('keeps polling a queued run and offers cancellation', async () => {
    const wrapper = shallowMount(RunDetailView, { props: { runId: 'r1' } })
    await flushPromises()
    const initialCalls = state.store.fetchRunDetail.mock.calls.length

    await vi.advanceTimersByTimeAsync(3000)
    expect(state.store.fetchRunDetail.mock.calls.length).toBe(initialCalls + 1)
    expect(wrapper.find('[data-testid="cancel-run"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows indeterminate ingest progress when the document total is unknown', async () => {
    state.store.currentRun.status = 'running'
    state.store.currentRun.current_stage = 'ingest'
    const wrapper = shallowMount(RunDetailView, { props: { runId: 'r1' } })
    await flushPromises()

    expect(wrapper.find('[data-testid="ingest-indeterminate"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('does not restart polling after unmounting during delayed resume', async () => {
    state.store.currentRun.status = 'awaiting_review'
    api.resumeRun.mockResolvedValue({ status: 'running' })
    const wrapper = shallowMount(RunDetailView, { props: { runId: 'r1' } })
    await flushPromises()
    await (wrapper.vm as unknown as { handleResume: () => Promise<void> }).handleResume()
    const callsBeforeUnmount = state.store.fetchRunDetail.mock.calls.length

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(2000)

    expect(state.store.fetchRunDetail.mock.calls.length).toBe(callsBeforeUnmount)
  })

  it('does not schedule polling when resume resolves after unmount', async () => {
    state.store.currentRun.status = 'awaiting_review'
    let resolveResume!: (value: { status: string }) => void
    api.resumeRun.mockImplementation(() => new Promise(resolve => { resolveResume = resolve }))
    const wrapper = shallowMount(RunDetailView, { props: { runId: 'r1' } })
    await flushPromises()

    const resumePromise = (wrapper.vm as unknown as { handleResume: () => Promise<void> }).handleResume()
    await flushPromises()
    const callsBeforeUnmount = state.store.fetchRunDetail.mock.calls.length
    wrapper.unmount()

    resolveResume({ status: 'running' })
    await resumePromise
    await vi.advanceTimersByTimeAsync(2000)

    expect(state.store.fetchRunDetail.mock.calls.length).toBe(callsBeforeUnmount)
  })
})
