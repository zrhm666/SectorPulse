import { useCallback } from 'react'
import { fetchRunComparison, type ComparisonPair } from '../runComparisonsApi'
import useComparisonRequest from './useComparisonRequest'

export default function useRunComparison(pair: ComparisonPair | null) {
  const base = pair?.base ?? '', compare = pair?.compare ?? ''
  const load = useCallback((signal: AbortSignal) => fetchRunComparison({ base, compare }, signal), [base, compare])
  return useComparisonRequest(pair ? JSON.stringify([base, compare]) : null, load)
}
