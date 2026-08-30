import { renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import useMediaQuery from './useMediaQuery'

afterEach(() => vi.unstubAllGlobals())

it('tracks media query changes and removes the exact listener on cleanup', () => {
  let listener: ((event: MediaQueryListEvent) => void) | undefined
  const addEventListener = vi.fn((_type: string, next: (event: MediaQueryListEvent) => void) => { listener = next })
  const removeEventListener = vi.fn()
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: true,
    media: '(max-width: 900px)',
    onchange: null,
    addEventListener,
    removeEventListener,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })))

  const { result, unmount } = renderHook(() => useMediaQuery('(max-width: 900px)'))
  expect(result.current).toBe(true)
  expect(addEventListener).toHaveBeenCalledWith('change', expect.any(Function))

  unmount()
  expect(removeEventListener).toHaveBeenCalledWith('change', listener)
})
