import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fetchRadar } from '../../api'
import RadarTab from './RadarTab'

vi.mock('../../api', () => ({ fetchRadar: vi.fn() }))

describe('RadarTab', () => {
  it('distinguishes request failure from an empty radar and allows retry', async () => {
    vi.mocked(fetchRadar)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ cards: [] })

    render(<RadarTab runId="run-1" />)

    expect(await screen.findByText('无法加载板块雷达')).toBeVisible()
    expect(screen.queryByText('暂无板块分析卡。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('暂无板块分析卡。')).toBeVisible()
    expect(fetchRadar).toHaveBeenCalledTimes(2)
  })
})
