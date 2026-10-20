import { Navigate, Route, Routes } from 'react-router-dom'

import { RequireAuth, RequireRole } from './components/Guards'
import { Shell } from './components/Shell'
import { AccountPage } from './pages/AccountPage'
import { AdminPage } from './pages/AdminPage'
import { AidePage } from './pages/AidePage'
import { AssurePage } from './pages/AssurePage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { ManagerPage } from './pages/ManagerPage'
import { PilotagePage } from './pages/PilotagePage'
import { ProPage } from './pages/ProPage'

export default function App() {
  return (
    <Routes>
      <Route path="/connexion" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="/compte" element={<AccountPage />} />
          <Route path="/aide" element={<AidePage />} />

          <Route element={<RequireRole roles={['assure'] } />}>
            <Route path="/assure" element={<AssurePage />} />
          </Route>

          <Route element={<RequireRole roles={['professionnel_sante'] } />}>
            <Route path="/professionnel" element={<ProPage />} />
          </Route>

          <Route element={<RequireRole roles={['gestionnaire'] } />}>
            <Route path="/gestionnaire" element={<ManagerPage />} />
          </Route>

          <Route element={<RequireRole roles={['administrateur'] } />}>
            <Route path="/administration" element={<AdminPage />} />
          </Route>

          {/* Le pilotage BI est ouvert au gestionnaire comme a l'administrateur :
              les indicateurs de fraude comme les KPI financiers les concernent. */}
          <Route element={<RequireRole roles={['gestionnaire', 'administrateur'] } />}>
            <Route path="/pilotage" element={<PilotagePage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
