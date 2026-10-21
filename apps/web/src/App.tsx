import { Navigate, Route, Routes } from 'react-router-dom'

import { RequireAuth, RequireRole } from './components/Guards'
import { Shell } from './components/Shell'
import { AccountPage } from './pages/AccountPage'
import { AidePage } from './pages/AidePage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { PilotagePage } from './pages/PilotagePage'
import { AccueilAdminPage } from './pages/administration/AccueilAdminPage'
import { CanauxPage } from './pages/administration/CanauxPage'
import { ComptesPage } from './pages/administration/ComptesPage'
import { JournalPage } from './pages/administration/JournalPage'
import { ModelePage } from './pages/administration/ModelePage'
import { ObservabilitePage } from './pages/administration/ObservabilitePage'
import { RgpdPage } from './pages/administration/RgpdPage'
import { SantePage } from './pages/administration/SantePage'
import { SeuilPage } from './pages/administration/SeuilPage'
import { AccueilAssurePage } from './pages/assure/AccueilAssurePage'
import { AssistantPage } from './pages/assure/AssistantPage'
import { RemboursementsPage } from './pages/assure/RemboursementsPage'
import { FileAlertesPage } from './pages/gestionnaire/FileAlertesPage'
import { HistoriquePage } from './pages/gestionnaire/HistoriquePage'
import { AccueilProPage } from './pages/professionnel/AccueilProPage'
import { DepotPage } from './pages/professionnel/DepotPage'
import { ImportLotPage } from './pages/professionnel/ImportLotPage'
import { OrdonnancePage } from './pages/professionnel/OrdonnancePage'
import { SuiviPage } from './pages/professionnel/SuiviPage'

export default function App() {
  return (
    <Routes>
      <Route path="/connexion" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="/compte" element={<AccountPage />} />
          <Route path="/aide" element={<AidePage />} />

          <Route element={<RequireRole roles={['assure']} />}>
            <Route path="/assure" element={<AccueilAssurePage />} />
            <Route path="/assure/remboursements" element={<RemboursementsPage />} />
            <Route path="/assure/assistant" element={<AssistantPage />} />
          </Route>

          <Route element={<RequireRole roles={['professionnel_sante']} />}>
            <Route path="/professionnel" element={<AccueilProPage />} />
            <Route path="/professionnel/depot" element={<DepotPage />} />
            <Route path="/professionnel/import-lot" element={<ImportLotPage />} />
            <Route path="/professionnel/suivi" element={<SuiviPage />} />
            <Route path="/professionnel/ordonnance" element={<OrdonnancePage />} />
          </Route>

          <Route element={<RequireRole roles={['gestionnaire']} />}>
            <Route path="/gestionnaire" element={<FileAlertesPage />} />
            <Route path="/gestionnaire/historique" element={<HistoriquePage />} />
          </Route>

          <Route element={<RequireRole roles={['administrateur']} />}>
            <Route path="/administration" element={<AccueilAdminPage />} />
            {/* Le lot du jury est multi-prestataires : un professionnel est
                borne a son propre prestataire par l'API, l'administrateur ne
                l'est pas. La route dediee evite d'ouvrir toutes les pages pro. */}
            <Route path="/administration/import-lot" element={<ImportLotPage />} />
            <Route path="/administration/seuil" element={<SeuilPage />} />
            <Route path="/administration/modele" element={<ModelePage />} />
            <Route path="/administration/sante" element={<SantePage />} />
            <Route path="/administration/canaux" element={<CanauxPage />} />
            <Route path="/administration/observabilite" element={<ObservabilitePage />} />
            <Route path="/administration/comptes" element={<ComptesPage />} />
            <Route path="/administration/journal" element={<JournalPage />} />
            <Route path="/administration/rgpd" element={<RgpdPage />} />
          </Route>

          {/* Le pilotage BI est ouvert au gestionnaire comme a l'administrateur :
              les indicateurs de fraude comme les KPI financiers les concernent. */}
          <Route element={<RequireRole roles={['gestionnaire', 'administrateur']} />}>
            <Route path="/pilotage" element={<PilotagePage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
