import { BrowserRouter, Route, Routes } from 'react-router-dom'
import RunDetailPage from './pages/RunDetailPage'
import RunListPage from './pages/RunListPage'
import DataRunPage from './pages/DataRunPage'

export default function App() {
  return (
    <BrowserRouter>
      <main className="app-layout">
        <Routes>
          <Route path="/" element={<RunListPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/data-runs/:runId" element={<DataRunPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
