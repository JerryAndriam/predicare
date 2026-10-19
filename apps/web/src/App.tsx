import { Navigate, Route, Routes } from 'react-router-dom'

import { RequireAuth, RequireRole } from './components/Guards'
import { Shell } from './components/Shell'
import { AdminPage } from './pages/AdminPage'
import { AssurePage } from './pages/AssurePage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { ManagerPage } from './pages/ManagerPage'
import { ProPage } from './pages/ProPage'

export default function App() {
  return (
    <Routes>
      <Route path="/connexion" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />

          <Route element={<RequireRole roles={['assure']} />}>
            <Route path="/assure" element={<AssurePage />} />
          </Route>

          <Route element={<RequireRole roles={['professionnel_sante']} />}>
            <Route path="/professionnel" element={<ProPage />} />
          </Route>

          <Route element={<RequireRole roles={['gestionnaire']} />}>
            <Route path="/gestionnaire" element={<ManagerPage />} />
          </Route>

          <Route element={<RequireRole roles={['administrateur']} />}>
            <Route path="/administration" element={<AdminPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
