// web/src/components/NewRunDialog.tsx
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createRun, fetchFixtureInput } from '../api'

export default function NewRunDialog({ onClose }: { onClose: () => void }) {
  const [jsonText, setJsonText] = useState('')
  const [provider, setProvider] = useState('fixture')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setJsonText(String(reader.result ?? ''))
    reader.readAsText(file)
  }

  async function handleStart() {
    setBusy(true)
    setError(null)
    try {
      const input = JSON.parse(jsonText)
      const { run_id } = await createRun(input, provider)
      onClose()
      nav(`/runs/${run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'JSON 无效或请求失败')
      setBusy(false)
    }
  }

  async function loadFixture() {
    try {
      setJsonText(JSON.stringify(await fetchFixtureInput(), null, 2))
      setProvider('fixture')
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载 Fixture 示例失败')
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-inner" onClick={(e) => e.stopPropagation()}>
        <h2>新建运行</h2>
        <div style={{ marginBottom: 8 }}>
          <button onClick={loadFixture}>加载 Fixture 示例</button>
          <button onClick={() => fileRef.current?.click()}>上传 JSON 文件</button>
          <input ref={fileRef} type="file" accept=".json" hidden onChange={handleFile} />
        </div>
        <textarea
          placeholder='粘贴 Phase 1B 输入 JSON，例如 {"requested_at":"...","contexts":[...],"gates":{...}}'
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
        />
        <div style={{ margin: '8px 0' }}>
          <label>Provider：</label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="fixture">fixture（默认，无需密钥）</option>
            <option value="live">live（需 consent + 环境变量）</option>
          </select>
        </div>
        {error && <p style={{ color: '#d93025' }}>{error}</p>}
        <div>
          <button disabled={busy} onClick={handleStart}>启动</button>
          <button disabled={busy} onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
