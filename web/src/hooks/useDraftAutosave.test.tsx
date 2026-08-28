import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ReviewApiError, type DraftPatchInput, type DraftPatchResponse } from '../editingApi'
import useDraftAutosave from './useDraftAutosave'

const field = { key: 'introduction', path: 'introduction', value: '旧导语' }

function Harness({ onSave }: { onSave: (input: DraftPatchInput) => Promise<DraftPatchResponse> }) {
  const autosave = useDraftAutosave({ version: 1, fields: [field], enabled: true, onSave })
  const state = autosave.fields.introduction
  return <>
    <textarea aria-label="导语" value={state.value} onChange={(event) => autosave.setValue('introduction', event.target.value)} onBlur={() => autosave.flush('introduction')} />
    <output aria-label="保存状态">{state.status}</output>
    <button onClick={() => autosave.retry('introduction')}>重试</button>
  </>
}

afterEach(() => {
  vi.useRealTimers()
})

it('saves 800ms after the last change and skips unchanged text', async () => {
  vi.useFakeTimers()
  const onSave = vi.fn().mockResolvedValue({ draft_id: 'draft-1', version: 2, status: 'READY_FOR_HUMAN_REVIEW', content: {} })
  render(<Harness onSave={onSave} />)

  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '新导语' } })
  await act(() => vi.advanceTimersByTimeAsync(799))
  expect(onSave).not.toHaveBeenCalled()
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(onSave).toHaveBeenCalledTimes(1)
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ base_version: 1, path: 'introduction', value: '新导语' }))
})

it('flushes a dirty field immediately on blur', async () => {
  vi.useFakeTimers()
  const onSave = vi.fn().mockResolvedValue({ draft_id: 'draft-1', version: 2, status: 'READY_FOR_HUMAN_REVIEW', content: {} })
  render(<Harness onSave={onSave} />)

  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '失焦保存' } })
  fireEvent.blur(screen.getByLabelText('导语'))
  await act(async () => undefined)
  expect(onSave).toHaveBeenCalledTimes(1)
})

it('queues newer text behind the in-flight save and rebases it on the returned version', async () => {
  vi.useFakeTimers()
  let resolveFirst: ((value: DraftPatchResponse) => void) | undefined
  const first = new Promise<DraftPatchResponse>((resolve) => { resolveFirst = resolve })
  const onSave = vi.fn()
    .mockReturnValueOnce(first)
    .mockResolvedValueOnce({ draft_id: 'draft-1', version: 3, status: 'READY_FOR_HUMAN_REVIEW', content: {} })
  render(<Harness onSave={onSave} />)

  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '第一版' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '第二版' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  expect(onSave).toHaveBeenCalledTimes(1)

  await act(async () => resolveFirst?.({ draft_id: 'draft-1', version: 2, status: 'READY_FOR_HUMAN_REVIEW', content: {} }))
  expect(onSave).toHaveBeenCalledTimes(2)
  expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ base_version: 2, value: '第二版' }))
})

it('retains local text and exposes conflict and failed states for retry', async () => {
  vi.useFakeTimers()
  const conflict = vi.fn().mockRejectedValue(new ReviewApiError('conflict', 409, 'CONFLICT'))
  const view = render(<Harness onSave={conflict} />)
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '不能丢失' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  expect(screen.getByLabelText('保存状态')).toHaveTextContent('conflict')
  expect(screen.getByLabelText('导语')).toHaveValue('不能丢失')

  view.unmount()
  const failed = vi.fn().mockRejectedValue(new Error('offline'))
  render(<Harness onSave={failed} />)
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '离线文本' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  expect(screen.getByLabelText('保存状态')).toHaveTextContent('failed')
  expect(screen.getByLabelText('导语')).toHaveValue('离线文本')
})
