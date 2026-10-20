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
Tester-Get "Factures assure" "/api/core/factures?limit=5" $tAssure | Out-Null
Tester-Get "References pro" "/api/core/factures/references" $tPro | Out-Null
Tester-Get "File alertes" "/api/core/alertes/file?statut=nouvelle&limit=100" $tGest | Out-Null
Tester-Get "Historique decisions" "/api/core/alertes/historique?limit=100" $tGest | Out-Null
Tester-Get "Admin seuil" "/api/core/admin/seuil" $tAdmin | Out-Null
Tester-Get "Admin modele" "/api/core/admin/modele" $tAdmin | Out-Null
Tester-Get "Admin sante" "/api/core/admin/sante" $tAdmin | Out-Null
Tester-Get "Admin canaux" "/api/core/admin/canaux" $tAdmin | Out-Null
Tester-Get "Admin utilisateurs" "/api/core/admin/utilisateurs" $tAdmin | Out-Null
Tester-Get "Audit journal" "/api/core/audit/journal?limit=5" $tAdmin | Out-Null
Tester-Get "Inference modele" "/api/inference/modele" $tAdmin | Out-Null

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
Write-Host "Rappel : l'assistant RAG renvoie 500 tant que LLM_API_KEY est un placeholder." -ForegroundColor Yellow
