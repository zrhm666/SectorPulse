import { useEffect, useState } from 'react'
import ShadowAcceptanceCard from '../components/ShadowAcceptanceCard'
import { fetchShadowRuns, type ShadowRunView } from '../shadowApi'

export default function ShadowAcceptancePage() {
  const [runs, setRuns] = useState<ShadowRunView[]>([])
  useEffect(() => { fetchShadowRuns().then(setRuns).catch(() => setRuns([])) }, [])
  return <ShadowAcceptanceCard runs={runs} />
}
