import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import DraftWorkspace from './DraftWorkspace'

const versions = [
  { version: 1, status: 'READY_FOR_HUMAN_REVIEW', titles: ['旧标题'], introduction: '旧导语', sections: [], conclusion: '旧结论', risk_notice: '旧风险', sources: [], character_count: 10 },
  { version: 2, status: 'READY_FOR_HUMAN_REVIEW', titles: ['标题'], introduction: '导语', sections: [], conclusion: '结论', risk_notice: '风险', sources: [], character_count: 10 },
]

afterEach(() => vi.useRealTimers())

it('navigates to a document field without remounting the editor', async () => {
  render(<DraftWorkspace versions={versions} onSave={vi.fn()} />)
  const conclusion = screen.getByLabelText('结论')
  await userEvent.selectOptions(screen.getByLabelText('跳转章节'), 'conclusion')
  expect(conclusion).toHaveFocus()
  expect(screen.getByLabelText('结论')).toBe(conclusion)
})

it('grows long text to its measured content height', () => {
  const height = vi.spyOn(HTMLTextAreaElement.prototype, 'scrollHeight', 'get').mockReturnValue(580)
  const view = render(<DraftWorkspace versions={versions} onSave={vi.fn()} />)
  expect(screen.getByLabelText('导语').style.height).toBe('582px')
  view.unmount()
  height.mockRestore()
})

it('autosaves the latest structured field without manual save buttons', async () => {
  vi.useFakeTimers()
  const onSave = vi.fn().mockResolvedValue({ draft_id: 'draft-1', version: 3, status: 'READY_FOR_HUMAN_REVIEW', content: {} })
  render(<DraftWorkspace versions={versions} onSave={onSave} />)

  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '新导语' } })
  expect(screen.queryByRole('button', { name: '保存导语' })).not.toBeInTheDocument()
  expect(screen.getByText('等待保存')).toBeVisible()
  await act(() => vi.advanceTimersByTimeAsync(800))
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ base_version: 2, path: 'introduction', value: '新导语' }))
})

it('keeps historical versions read-only and outside autosave', async () => {
  const onSave = vi.fn()
  render(<DraftWorkspace versions={versions} onSave={onSave} />)
  await userEvent.selectOptions(screen.getByLabelText('查看草稿版本'), '1')

  expect(screen.getByLabelText('导语')).toHaveValue('旧导语')
  expect(screen.getByLabelText('导语')).toHaveAttribute('readonly')
  expect(screen.getByText(/不会触发自动保存/)).toBeVisible()
  expect(onSave).not.toHaveBeenCalled()
})

it('retains text and offers retry after a failed autosave', async () => {
  vi.useFakeTimers()
  const onSave = vi.fn().mockRejectedValue(new Error('offline'))
  render(<DraftWorkspace versions={versions} onSave={onSave} />)
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '离线文本' } })
  await act(() => vi.advanceTimersByTimeAsync(800))

  expect(screen.getByLabelText('导语')).toHaveValue('离线文本')
  expect(screen.getByRole('button', { name: '重试保存导语' })).toBeEnabled()
})

it('emits the focused section and its persisted source mapping', () => {
  const onFocusField = vi.fn()
  const mappedVersions = [{
    ...versions[1],
    sections: [{ section_id: 'agri', heading: '农业板块', body: '正文', source_ids: ['source-2'] }],
  }]
  render(<DraftWorkspace versions={mappedVersions} onSave={vi.fn()} onFocusField={onFocusField} />)

  fireEvent.focus(screen.getByLabelText('农业板块'))
  expect(onFocusField).toHaveBeenCalledWith({ key: 'sections/agri/body', label: '农业板块', sourceIds: ['source-2'] })
})
