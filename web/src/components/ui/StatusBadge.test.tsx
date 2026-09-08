import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import StatusBadge from './StatusBadge'

it('presents collection as an active Chinese status without hiding the original code', () => {
  render(<StatusBadge status="FETCHING_MARKET" />)
  expect(screen.getByText('采集行情').closest('[data-status]')).toHaveAttribute('data-tone', 'info')
  expect(screen.getByText('采集行情').closest('[data-status]')).toHaveAttribute('data-status', 'FETCHING_MARKET')
})
