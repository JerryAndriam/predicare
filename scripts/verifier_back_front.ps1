# =============================================================================
# Verification back / front PrediCare
# -----------------------------------------------------------------------------
# Usage :
#   powershell -ExecutionPolicy Bypass -File .\scripts\verifier_back_front.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\verifier_back_front.ps1 -MotDePasse "MonMotDePasse"
#
# Le script :
#   1. connecte les 4 comptes de demonstration ;
#   2. teste les endpoints de chaque ecran ;
#   3. soumet une facture et verifie la prediction en base ;
#   4. verifie la file d'alertes et enregistre une decision si possible ;
#   5. affiche un rapport OK / KO.
# =============================================================================

param(
    [string]$Base = "http://localhost:8080",
    [string]$MotDePasse = "PrediCare2026!"
)

$ErrorActionPreference = "SilentlyContinue"
$script:ok = 0
$script:ko = 0

function Ecrire-Ok([string]$texte) {
    Write-Host ("  [OK]  " + $texte) -ForegroundColor Green
    $script:ok++
}
function Ecrire-Ko([string]$texte) {
    Write-Host ("  [KO]  " + $texte) -ForegroundColor Red
    $script:ko++
}
function Ecrire-Titre([string]$texte) {
    Write-Host ""
    Write-Host ("=== " + $texte + " ===") -ForegroundColor Cyan
}

function Connexion([string]$email) {
    $corps = @{ email = $email; password = $MotDePasse } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Uri "$Base/api/core/auth/login" -Method Post -Body $corps -ContentType "application/json" -TimeoutSec 20
        if ($r.access_token) {
            Ecrire-Ok ("login " + $email)
            return $r.access_token
        }
    } catch { }
    Ecrire-Ko ("login " + $email)
    return $null
}

function Tester-Get([string]$nom, [string]$chemin, [string]$token) {
    $headers = @{ Authorization = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri "$Base$chemin" -Headers $headers -UseBasicParsing -TimeoutSec 20
        Ecrire-Ok ("$nom -> " + $r.StatusCode + " " + $chemin)
        return $r
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if (-not $code) { $code = "ERR" }
        Ecrire-Ko ("$nom -> " + $code + " " + $chemin)
        return $null
    }
}

function Tester-Post([string]$nom, [string]$chemin, [string]$token, [string]$corps) {
    $headers = @{ Authorization = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri "$Base$chemin" -Method Post -Headers $headers -Body $corps -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
        Ecrire-Ok ("$nom -> " + $r.StatusCode)
        return $r
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if (-not $code) { $code = "ERR" }
        Ecrire-Ko ("$nom -> " + $code)
        if ($_.ErrorDetails.Message) {
            Write-Host ("        " + $_.ErrorDetails.Message) -ForegroundColor DarkYellow
        }
        return $null
    }
}

function Sql([string]$requete) {
    return (& docker compose -f docker-compose.yml exec -T db psql -U predicare -d predicare -tAc $requete 2>$null).Trim()
}

Write-Host "PrediCare - verification back / front" -ForegroundColor White
Write-Host ("Base : " + $Base)

# ---------------------------------------------------------------- connexions
Ecrire-Titre "1. Connexion des 4 comptes"
$tAssure = Connexion "assure@predicare.local"
$tPro = Connexion "pro@predicare.local"
$tGest = Connexion "gestionnaire@predicare.local"
$tAdmin = Connexion "admin@predicare.local"

if (-not $tAdmin) {
    Write-Host "Impossible de continuer sans le compte admin." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- endpoints
Ecrire-Titre "2. Endpoints par ecran"

Tester-Get "Profil admin" "/api/core/auth/me" $tAdmin | Out-Null

$repFactures = Tester-Get "Factures assure" "/api/core/factures?limit=100" $tAssure
if ($repFactures) {
    $ficheAssure = $repFactures.Content | ConvertFrom-Json
    $pseudos = @($ficheAssure.items | ForEach-Object { $_.assure_pseudonyme } | Sort-Object -Unique)
    if ($pseudos.Count -eq 1 -and $ficheAssure.items.Count -gt 0) {
        Ecrire-Ok ("Isolation assure : un seul dossier (" + $pseudos[0] + ")")
    } else {
        Ecrire-Ko ("Isolation assure : " + $pseudos.Count + " dossier(s) different(s)")
    }

    $attenduAssure = [int](Sql "SELECT count(*) FROM core.facture f JOIN core.utilisateur u ON u.assured_id = f.assure_id WHERE u.email = 'assure@predicare.local';")
    if ($ficheAssure.items.Count -eq $attenduAssure) {
        Ecrire-Ok ("Factures du dossier : " + $attenduAssure + " (aucune fuite)")
    } else {
        Ecrire-Ko ("Factures du dossier : API=" + $ficheAssure.items.Count + " SQL=" + $attenduAssure)
    }

    $payeesAvecMontant = @($ficheAssure.items | Where-Object {
        $_.statut -eq "PAYEE" -and $null -ne $_.montant_pris_en_charge
    })
    if ($payeesAvecMontant.Count -gt 0) {
        Ecrire-Ok ("Montants de prise en charge presents : " + $payeesAvecMontant.Count + " facture(s) PAYEE")
    } else {
        Ecrire-Ko "Montants de prise en charge absents"
    }
}

$repRefsPro = Tester-Get "References pro" "/api/core/factures/references" $tPro
$prestatairePro = $null
if ($repRefsPro) {
    $refsPro = $repRefsPro.Content | ConvertFrom-Json
    $prestatairePro = $refsPro.prestataire_du_compte
    if ($prestatairePro -and $refsPro.prestataires.Count -eq 1) {
        Ecrire-Ok ("Perimetre pro declare : " + $prestatairePro)
    } else {
        Ecrire-Ko ("Perimetre pro absent ou multiple : " + $refsPro.prestataires.Count)
    }
}

$repFacturesPro = Tester-Get "Factures pro (perimetre)" "/api/core/factures?limit=5" $tPro
if ($repFacturesPro -and $prestatairePro) {
    $pagePro = $repFacturesPro.Content | ConvertFrom-Json
    $horsPerimetre = @($pagePro.items | Where-Object { $_.prestataire_id -ne $prestatairePro })
    if ($horsPerimetre.Count -eq 0 -and $pagePro.total -gt $pagePro.items.Count) {
        Ecrire-Ok ("Aucune fuite inter-prestataires (total=" + $pagePro.total + ", page=" + $pagePro.items.Count + ")")
    } else {
        Ecrire-Ko ("Perimetre pro : " + $horsPerimetre.Count + " fuite(s), total=" + $pagePro.total)
    }
}

Tester-Get "File alertes" "/api/core/alertes/file?statut=nouvelle&limit=100" $tGest | Out-Null
Tester-Get "Historique decisions" "/api/core/alertes/historique?limit=100" $tGest | Out-Null
Tester-Get "Admin seuil" "/api/core/admin/seuil" $tAdmin | Out-Null
Tester-Get "Admin modele" "/api/core/admin/modele" $tAdmin | Out-Null

$repSante = Tester-Get "Admin sante" "/api/core/admin/sante" $tAdmin
if ($repSante) {
    $sante = $repSante.Content | ConvertFrom-Json
    $proprietesRag = @($sante.dependances.rag.PSObject.Properties.Name)
    if ($proprietesRag -contains "documents" -and $proprietesRag -contains "embedding_configure") {
        Ecrire-Ok ("Sante RAG detaillee : statut=" + $sante.dependances.rag.status +
            ", documents=" + $sante.dependances.rag.documents +
            ", embeddings=" + $sante.dependances.rag.embedding_configure)
    } else {
        Ecrire-Ko "Sante RAG sans detail documents/embeddings"
    }
}

$repCanaux = Tester-Get "Admin canaux" "/api/core/admin/canaux" $tAdmin
if ($repCanaux) {
    # PowerShell 5.1 : le resultat d'un `ConvertFrom-Json` sur un tableau JSON
    # arrive dans le pipeline comme un objet unique. On l'affecte d'abord,
    # sinon `@(...)` emballe le tableau dans un element et la boucle
    # `Where-Object` ne voit jamais les canaux.
    $canaux = $repCanaux.Content | ConvertFrom-Json
    $canaux = @($canaux)
    $avecConfigure = @($canaux | Where-Object { $_.PSObject.Properties.Name -contains "configure" })
    if ($avecConfigure.Count -eq $canaux.Count -and $canaux.Count -gt 0) {
        Ecrire-Ok ("Canaux avec etat de configuration : " + $canaux.Count)
    } else {
        Ecrire-Ko "Canaux sans champ configure"
    }
}

Tester-Get "Admin utilisateurs" "/api/core/admin/utilisateurs" $tAdmin | Out-Null
Tester-Get "Audit journal" "/api/core/audit/journal?limit=5" $tAdmin | Out-Null
Tester-Get "Inference modele" "/api/inference/modele" $tAdmin | Out-Null
Tester-Post "Assistant RAG (degrade ou configure)" "/api/rag/question" $tAssure '{"question":"Quelles sont les conditions de remboursement ?"}' | Out-Null

$repObs = Tester-Get "Admin observabilite" "/api/core/admin/observabilite" $tAdmin
if ($repObs) {
    $obs = $repObs.Content | ConvertFrom-Json
    $blocs = @("base", "inference", "derive", "rag")
    $manquants = @($blocs | Where-Object { $obs.PSObject.Properties.Name -notcontains $_ })
    if ($manquants.Count -eq 0) {
        Ecrire-Ok ("Observabilite : latence, volume, erreurs et derive exposes (base=" +
            $obs.base.factures + " factures, latence dispo=" +
            $obs.inference.latence_ms.disponible + ")")
    } else {
        Ecrire-Ko ("Observabilite incomplete : " + ($manquants -join ", "))
    }
}

# ---------------------------------------------------------------- soumission
Ecrire-Titre "3. Soumission d'une facture (bout en bout)"

$avant = [int](Sql "SELECT count(*) FROM ml.prediction;")

try {
    $refs = Invoke-RestMethod -Uri "$Base/api/core/factures/references" -Headers @{ Authorization = "Bearer $tPro" } -TimeoutSec 20
    $assure = $refs.assures[0].pseudonyme
    $prestataire = $refs.prestataires[0].code
    # Le schema impose un montant unitaire <= 10 000 EUR : beaucoup d'actes
    # forfaitaires (cesarienne, IRM, prothese) depassent ce plafond.
    $actesValides = @($refs.actes | Where-Object {
        [double]$_.prix_unitaire -gt 0 -and [double]$_.prix_unitaire -le 10000
    })
    if ($actesValides.Count -eq 0) {
        throw "Aucun acte avec un prix unitaire <= 10 000 EUR."
    }
    $acte = $actesValides[0]
    $prix = [double]$acte.prix_unitaire
    $maintenant = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")

    $facture = @{
        assure_pseudonyme = $assure
        prestataire_id    = $prestataire
        date_facture      = $maintenant
        montant_total     = $prix
        lignes            = @(
            @{
                code_acte      = $acte.code
                quantite       = 1
                montant_unitaire = $prix
                date_acte      = $maintenant
            }
        )
    } | ConvertTo-Json -Depth 5

    $r = Tester-Post "Soumettre facture" "/api/core/factures/soumettre" $tPro $facture
    if ($r) {
        $resultat = $r.Content | ConvertFrom-Json
        Write-Host ("        facture_id      : " + $resultat.facture_id) -ForegroundColor Gray
        Write-Host ("        score_fraude    : " + [math]::Round($resultat.score_fraude, 4)) -ForegroundColor Gray
        Write-Host ("        is_fraud        : " + $resultat.is_fraud) -ForegroundColor Gray
        Write-Host ("        seuil_applique  : " + [math]::Round($resultat.seuil_applique, 4)) -ForegroundColor Gray
        Write-Host ("        model_version   : " + $resultat.model_version) -ForegroundColor Gray
        Write-Host ("        contributions   : " + $resultat.shap.Count) -ForegroundColor Gray
    }
} catch {
    Ecrire-Ko "Soumission facture (references indisponibles)"
}

$apres = [int](Sql "SELECT count(*) FROM ml.prediction;")
if ($apres -gt $avant) {
    Ecrire-Ok ("Prediction en base : " + $avant + " -> " + $apres)
} else {
    Ecrire-Ko ("Prediction en base inchangee : " + $avant)
}

# ---------------------------------------------------------------- alerte
Ecrire-Titre "4. File d'alertes et decision"

try {
    $file = Invoke-RestMethod -Uri "$Base/api/core/alertes/file?statut=nouvelle&limit=10" -Headers @{ Authorization = "Bearer $tGest" } -TimeoutSec 20
    if ($file.Count -gt 0) {
        Ecrire-Ok ("Alertes en attente : " + $file.Count)
        $alerte = $file[0]
        Write-Host ("        prediction_id : " + $alerte.prediction_id) -ForegroundColor Gray
        Write-Host ("        score         : " + [math]::Round($alerte.score_fraude, 4)) -ForegroundColor Gray
        Tester-Get "Detail alerte" ("/api/core/alertes/detail/" + $alerte.prediction_id) $tGest | Out-Null

        $decision = @{
            prediction_id = [string]$alerte.prediction_id
            decision      = "valider_fraude"
            commentaire   = "Verification automatique du script de test."
            decided_at    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        } | ConvertTo-Json
        Tester-Post "Enregistrer decision" "/api/core/alertes/decision" $tGest $decision | Out-Null
    } else {
        Write-Host "  [--]  Aucune alerte en attente." -ForegroundColor Yellow
        Write-Host "        Le score de la facture est peut-etre sous le seuil." -ForegroundColor Gray
        Write-Host "        Pour forcer une alerte : Admin -> Seuil -> 0.05, puis relancer." -ForegroundColor Gray
    }
} catch {
    Ecrire-Ko "Lecture de la file d'alertes"
}

# ---------------------------------------------------------------- ordonnance
Ecrire-Titre "4bis. Ordonnance enrichie et detection de doublon"

try {
    $refs = Invoke-RestMethod -Uri "$Base/api/core/factures/references" -Headers @{ Authorization = "Bearer $tPro" } -TimeoutSec 20
    $assureOrd = $refs.assures[0].pseudonyme
    $prestataireOrd = $refs.prestataires[0].code

    # On cherche un couple (assure, acte) pour lequel AUCUNE ordonnance
    # n'existe deja AUJOURD'HUI : le controle de doublon porte sur ce
    # triplet, et le script doit pouvoir etre relance le meme jour sans
    # buter sur sa propre run precedente.
    $acteOrd = $null
    foreach ($candidat in @($refs.actes | Where-Object { [double]$_.prix_unitaire -gt 0 })) {
        $deja = [int](Sql ("SELECT count(*) FROM core.ordonnance o JOIN core.acte a ON a.id = o.acte_id JOIN core.assure s ON s.id = o.assure_id WHERE s.pseudonyme = '" + $assureOrd + "' AND a.code = '" + $candidat.code + "' AND CAST(o.date_ordonnance AS date) = CURRENT_DATE;"))
        if ($deja -eq 0) { $acteOrd = $candidat; break }
    }
    if (-not $acteOrd) {
        throw "Aucun acte libre pour ce dossier aujourd'hui."
    }
    $maintenantOrd = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")

    # Nettoyage des ordonnances de test LANCEES PAR CE SCRIPT les jours
    # precedents : le controle de doublon porte sur (assure, acte, jour), il
    # refuserait donc un second passage du script a 24 h d'intervalle. On
    # ne supprime que CE QUE LE SCRIPT A CREE (reference prefixee), jamais
    # une ordonnance metier. Les factures liees sont d'abord liberees :
    # la liaison facture <-> ordonnance est une cle etrangere.
    Sql ("UPDATE core.facture SET ordonnance_id = NULL WHERE ordonnance_id IN (SELECT id FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%');") | Out-Null
    Sql ("DELETE FROM core.ordonnance_ligne WHERE ordonnance_id IN (SELECT id FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%');") | Out-Null
    Sql ("DELETE FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%';") | Out-Null

    $ordonnance = @{
        assure_pseudonyme = $assureOrd
        prestataire_id    = $prestataireOrd
        code_acte         = $acteOrd.code
        date_ordonnance   = $maintenantOrd
        quantite          = 1
        reference         = "ORD-TEST-" + (Get-Date).ToString("yyyyMMddHHmmss")
        diagnostic        = "Lombalgie aigue"
        validite_jours    = 45
    } | ConvertTo-Json

    $rOrd = Tester-Post "Depot ordonnance (diagnostic + validite)" "/api/core/factures/ordonnances" $tPro $ordonnance
    if ($rOrd) {
        $ord = $rOrd.Content | ConvertFrom-Json
        $enBase = Sql ("SELECT count(*) FROM core.ordonnance o JOIN core.ordonnance_ligne ol ON ol.ordonnance_id = o.id WHERE o.reference = '" + $ord.reference + "';")
        $avecLigne = [int]$enBase
        if ($avecLigne -gt 0) {
            Ecrire-Ok ("Ordonnance " + $ord.reference + " : ligne de prescription enregistree")
        } else {
            Ecrire-Ko ("Ordonnance " + $ord.reference + " : aucune ligne de prescription")
        }
    }

    # Le meme dossier, le meme acte, le meme jour : le doublon doit etre refuse.
    try {
        Invoke-WebRequest -Uri "$Base/api/core/factures/ordonnances" -Method Post -Headers @{ Authorization = "Bearer $tPro" } -Body $ordonnance -ContentType "application/json" -UseBasicParsing -TimeoutSec 20 | Out-Null
        Ecrire-Ko "Doublon d'ordonnance accepte (il devait etre refuse)"
    } catch {
        $codeDoublon = $_.Exception.Response.StatusCode.value__
        if ($codeDoublon -eq 409) {
            Ecrire-Ok "Doublon d'ordonnance refuse (409)"
        } else {
            Ecrire-Ko ("Doublon d'ordonnance : code " + $codeDoublon)
        }
    }

    # Nettoyage final : le script ne doit pas laisser de trace en base.
    Sql ("UPDATE core.facture SET ordonnance_id = NULL WHERE ordonnance_id IN (SELECT id FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%');") | Out-Null
    Sql ("DELETE FROM core.ordonnance_ligne WHERE ordonnance_id IN (SELECT id FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%');") | Out-Null
    Sql ("DELETE FROM core.ordonnance WHERE reference LIKE 'ORD-TEST-%';") | Out-Null
} catch {
    Ecrire-Ko "Depot ordonnance (references indisponibles)"
}

# ---------------------------------------------------------------- base
Ecrire-Titre "5. Etat de la base"
Write-Host ("  factures      : " + (Sql "SELECT count(*) FROM core.facture;"))
Write-Host ("  predictions   : " + (Sql "SELECT count(*) FROM ml.prediction;"))
Write-Host ("  shap          : " + (Sql "SELECT count(*) FROM ml.shap_explication;"))
Write-Host ("  decisions     : " + (Sql "SELECT count(*) FROM audit.decision_gestionnaire;"))
Write-Host ("  comptes       : " + (Sql "SELECT count(*) FROM core.utilisateur;"))
Write-Host ("  journal       : " + (Sql "SELECT count(*) FROM audit.journal;"))

# ---------------------------------------------------------------- bilan
Ecrire-Titre "Bilan"
Write-Host ("  OK : " + $script:ok) -ForegroundColor Green
Write-Host ("  KO : " + $script:ko) -ForegroundColor Red
Write-Host ""
Write-Host "Rappel : l'assistant RAG repond en mode degrade (200, succes=false) tant que LLM_API_KEY et EMBEDDING_API_KEY sont des placeholders ; /admin/sante le signale." -ForegroundColor Yellow
