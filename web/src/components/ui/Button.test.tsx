import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import Button from './Button'

it('renders a primary action with an optional decorative icon', () => {
  render(<Button icon="plus">新建分析</Button>)
  const button = screen.getByRole('button', { name: '新建分析' })
  expect(button).toHaveAttribute('data-variant', 'primary')
  expect(button.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('disables a loading action and announces its state', () => {
  const onClick = vi.fn()
  render(<Button loading loadingLabel="正在保存" onClick={onClick}>保存</Button>)
  const button = screen.getByRole('button', { name: '正在保存' })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute('aria-busy', 'true')
})
