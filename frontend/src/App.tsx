import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { CompanyInsightsProvider } from './hooks/useCompanyInsights'
import { HomePage } from './pages/HomePage'
import { InsightsPage } from './pages/InsightsPage'

export default function App() {
  return (
    <BrowserRouter>
      <CompanyInsightsProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="insights" element={<InsightsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </CompanyInsightsProvider>
    </BrowserRouter>
  )
}
