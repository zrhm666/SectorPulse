import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ReviewEditor from './ReviewEditor'

describe('ReviewEditor', () => {
  it('renders editable section and save action', () => {
    render(
      <ReviewEditor
        runId="run-1"
        draftId="draft-1"
        version={1}
        sectionId="intro"
        heading="导语"
        body="原文"
        onSaved={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('导语')).toHaveValue('原文')
    expect(screen.getByRole('button', { name: '保存修改' })).toBeInTheDocument()
  })
})
