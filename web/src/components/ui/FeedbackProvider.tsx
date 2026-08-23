import { createContext, type ReactNode, useContext, useMemo, useState } from 'react'

type Tone = 'success' | 'error'
type FeedbackApi = { success: (message: string) => void; error: (message: string) => void }
type Notice = { id: number; tone: Tone; message: string }

const FeedbackContext = createContext<FeedbackApi | null>(null)

export function useFeedback(): FeedbackApi {
  return useContext(FeedbackContext) ?? { success: () => undefined, error: () => undefined }
}

export default function FeedbackProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
  const api = useMemo(() => {
    const add = (tone: Tone, message: string) => {
      const id = Date.now() + Math.random()
      setNotices((items) => [...items, { id, tone, message }])
      window.setTimeout(() => setNotices((items) => items.filter((item) => item.id !== id)), 5000)
    }
    return { success: (message: string) => add('success', message), error: (message: string) => add('error', message) }
  }, [])

  return <FeedbackContext.Provider value={api}>
    {children}
    <div className="feedback-stack" aria-live="polite">
      {notices.map((notice) => <div className={`feedback feedback--${notice.tone}`} role="status" key={notice.id}><span>{notice.message}</span><button type="button" aria-label="关闭通知" onClick={() => setNotices((items) => items.filter((item) => item.id !== notice.id))}>关闭</button></div>)}
    </div>
  </FeedbackContext.Provider>
}
