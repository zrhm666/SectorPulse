import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import FeedbackProvider, { useFeedback } from './FeedbackProvider'

function Demo() {
  const feedback = useFeedback()
  return <><button onClick={() => feedback.success('版本已保存')}>成功</button><button onClick={() => feedback.error('保存失败')}>失败</button></>
}

it('announces and dismisses operation feedback', async () => {
  render(<FeedbackProvider><Demo /></FeedbackProvider>)
  await userEvent.click(screen.getByRole('button', { name: '成功' }))
  expect(screen.getByRole('status')).toHaveTextContent('版本已保存')
  await userEvent.click(screen.getByRole('button', { name: '关闭通知' }))
  expect(screen.queryByText('版本已保存')).not.toBeInTheDocument()
})
