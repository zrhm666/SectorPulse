import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import type { DataRunView } from '../../dataRunsApi'
import DataRunActionPanel from './DataRunActionPanel'

it('offers one generation action without an execution-mode choice', () => {
  const generate = vi.fn()
  render(<MemoryRouter><DataRunActionPanel
    run={{ run_id: 'r1', status: 'READY_FOR_ATTRIBUTION' } as DataRunView}
    contentRun={null} busy={false} error={null} candidateCount={3}
    candidatesLoading={false} onGenerate={generate} onRetry={vi.fn()}
    onCancel={vi.fn()} cancelling={false}
  /></MemoryRouter>)
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '生成分析稿' }))
  expect(generate).toHaveBeenCalledWith()
})
