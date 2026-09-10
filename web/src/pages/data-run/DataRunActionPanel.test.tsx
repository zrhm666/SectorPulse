import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import type { DataRunView } from '../../dataRunsApi'
import DataRunActionPanel from './DataRunActionPanel'

it('defaults to workflow and passes the chosen Agent mode to generation', () => {
  const generate = vi.fn()
  render(<MemoryRouter><DataRunActionPanel
    run={{ run_id: 'r1', status: 'READY_FOR_ATTRIBUTION' } as DataRunView}
    contentRun={null} busy={false} error={null} candidateCount={3}
    candidatesLoading={false} onGenerate={generate} onRetry={vi.fn()}
    onCancel={vi.fn()} cancelling={false}
  /></MemoryRouter>)
  expect(screen.getByRole('radio', { name: /工作流模式/ })).toBeChecked()
  fireEvent.click(screen.getByRole('radio', { name: /Agent 模式/ }))
  fireEvent.click(screen.getByRole('button', { name: '生成分析稿' }))
  expect(generate).toHaveBeenCalledWith('agent')
})
