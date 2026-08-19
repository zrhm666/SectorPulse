import { useEffect, useState } from 'react'
import ShadowAcceptanceCard from '../components/ShadowAcceptanceCard'
import { fetchShadowProgress, fetchShadowRuns, type ShadowProgress, type ShadowRunView } from '../shadowApi'

export default function ShadowAcceptancePage() {
  const [runs, setRuns] = useState<ShadowRunView[]>([])
  const [progress, setProgress] = useState<ShadowProgress>()
  useEffect(() => {
    fetchShadowRuns().then(setRuns).catch(() => setRuns([]))
    fetchShadowProgress().then(setProgress).catch(() => setProgress(undefined))
  }, [])
  return <ShadowAcceptanceCard runs={runs} progress={progress} />
}
