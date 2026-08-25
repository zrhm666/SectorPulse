import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import AppIcon from './AppIcon'

it('keeps decorative icons out of the accessibility tree', () => {
  const { container } = render(<AppIcon name="home" />)
  expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('gives standalone icons an accessible title', () => {
  render(<AppIcon name="refresh" label="刷新" />)
  expect(screen.getByRole('img', { name: '刷新' })).toBeInTheDocument()
})
