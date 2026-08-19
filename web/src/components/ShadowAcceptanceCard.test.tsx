import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ShadowAcceptanceCard from './ShadowAcceptanceCard'

describe('ShadowAcceptanceCard', () => {
  it('shows 20 day progress', () => {
    render(<ShadowAcceptanceCard runs={[]} />)
    expect(screen.getByText('交易日进度：0/20')).toBeInTheDocument()
  })
})
