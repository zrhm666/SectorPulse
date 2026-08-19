import { BrowserRouter, Route, Routes } from 'react-router-dom'
import RunDetailPage from './pages/RunDetailPage'
import RunListPage from './pages/RunListPage'
import DataRunPage from './pages/DataRunPage'
import SchedulePage from './pages/SchedulePage'
import TaskRunPage from './pages/TaskRunPage'

export default function App() {
  return (
    <BrowserRouter>
      <main className="app-layout">
        <Routes>
          <Route path="/" element={<RunListPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/data-runs/:runId" element={<DataRunPage />} />
          <Route path="/schedules" element={<SchedulePage />} />
          <Route path="/task-runs/:runId" element={<TaskRunPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
