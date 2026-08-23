import { BrowserRouter, Route, Routes } from 'react-router-dom'
import AppShell from './layout/AppShell'
import RunDetailPage from './pages/RunDetailPage'
import RunListPage from './pages/RunListPage'
import DataRunPage from './pages/DataRunPage'
import SchedulePage from './pages/SchedulePage'
import TaskRunPage from './pages/TaskRunPage'
import ShadowAcceptancePage from './pages/ShadowAcceptancePage'
import OperationsDashboardPage from './pages/OperationsDashboardPage'
import SystemStatusPage from './pages/SystemStatusPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OperationsDashboardPage />} />
        <Route path="/runs" element={<RunListPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/data-runs/:runId" element={<DataRunPage />} />
        <Route path="/schedules" element={<SchedulePage />} />
        <Route path="/task-runs/:runId" element={<TaskRunPage />} />
        <Route path="/shadow-acceptance" element={<ShadowAcceptancePage />} />
        <Route path="/system" element={<SystemStatusPage />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
