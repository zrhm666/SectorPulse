import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SchedulePage from './SchedulePage'
import * as api from '../schedulesApi'

vi.mock('../schedulesApi')

describe('SchedulePage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchSchedules).mockResolvedValue([
      { schedule_id: 'schedule-1', name: '盘后', mode: 'post_close', timezone: 'Asia/Shanghai', local_time: '16:00', trading_days: 'weekdays', enabled: true, next_run_at: null },
    ])
    vi.mocked(api.triggerSchedule).mockResolvedValue({ run_id: 'run-1' })
  })

  it('shows next trigger and allows manual trigger', async () => {
    render(<MemoryRouter><SchedulePage /></MemoryRouter>)
    expect(await screen.findByText(/下一次触发/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '立即运行' }))
    expect(api.triggerSchedule).toHaveBeenCalledWith('schedule-1')
  })

  it('shows a loading state while schedules are being requested', () => {
    vi.mocked(api.fetchSchedules).mockReturnValue(new Promise(() => undefined))

    render(<MemoryRouter><SchedulePage /></MemoryRouter>)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载调度计划')
  })

  it('shows a request error when schedules cannot be loaded', async () => {
    vi.mocked(api.fetchSchedules).mockRejectedValue(new Error('offline'))

    render(<MemoryRouter><SchedulePage /></MemoryRouter>)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载调度计划')
  })

  it('shows a guided empty state after a successful empty response', async () => {
    vi.mocked(api.fetchSchedules).mockResolvedValue([])

    render(<MemoryRouter><SchedulePage /></MemoryRouter>)

    expect(await screen.findByRole('heading', { level: 2, name: '还没有调度计划' })).toBeInTheDocument()
  })
})
