import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ShadowAcceptanceCard from './ShadowAcceptanceCard'

describe('ShadowAcceptanceCard', () => {
  it('shows 20 day progress', () => {
    render(<ShadowAcceptanceCard runs={[]} progress={{ trading_days: 1, passed: 1, failed: 0, blocked: 0, remaining: 19, complete: false }} />)
    expect(screen.getByText('交易日进度：1/20')).toBeInTheDocument()
  })
})
