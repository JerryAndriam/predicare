"""Passe d'accentuation des libelles du front.

Le projet a fait le choix d'ecrire les libelles en ASCII. Pour un livrable
francophone presente a un jury, c'est un signal de finission inachevee :
« Se deconnecter », « Modele », « A traiter » se remarquent aussitot.

Ce script accentue les textes AFFICHES, et rien d'autre. Les regles sont
volontairement severes :

- le texte JSX (entre `>` et `<`) est accentue ;
- un litteral de chaine est accentue seulement s'il ne ressemble pas a une
  valeur technique (pas de `_`, `/`, `{`, `}`, `:`, `=`) ;
- un attribut JSX n'est accentue que s'il porte du TEXTE (label, aide,
  placeholder, title, alt, aria-label) ; tous les autres sont techniques
  (class, id, href, role, aria-controls...) et restent inchanges ;
- le typecheck TypeScript est le garde-fou final : un identifiant casse
  devient une erreur de compilation, pas un bug silencieux.

Usage :
    python scripts/accents_front.py            # applique
    python scripts/accents_front.py --verifier # liste ce qui reste
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"

#: Mots francais a accentuer, et leur forme correcte.
DICTIONNAIRE: dict[str, str] = {
    # voyelles accentuables
    "a": "a",  # placeholder : gere par les expressions multi-mots
    "apres": "après",
    "arret": "arrêt",
    "attribuee": "attribuée",
    "attribuees": "attribuées",
    "caractere": "caractère",
    "caracteres": "caractères",
    "chaine": "chaîne",
    "chaines": "chaînes",
    "classe": "classe",
    "cle": "clé",
    "cles": "clés",
    "coherence": "cohérence",
    "complet": "complet",
    "controle": "contrôle",
    "controles": "contrôles",
    "controlee": "contrôlée",
    "cote": "côté",
    "cout": "coût",
    "couts": "coûts",
    "cree": "créé",
    "creee": "créée",
    "creees": "créées",
    "dedie": "dédié",
    "demonstration": "démonstration",
    "deja": "déjà",
    "delai": "délai",
    "delais": "délais",
    "depose": "déposé",
    "deposee": "déposée",
    "deposees": "déposées",
    "depot": "dépôt",
    "depots": "dépôts",
    "derive": "dérive",
    "detaille": "détaillé",
    "developpe": "développé",
    "donnee": "donnée",
    "donnees": "données",
    "pseudonymise": "pseudonymisé",
    "pseudonymisee": "pseudonymisée",
    "pseudonymisees": "pseudonymisées",
    "numero": "numéro",
    "parametre": "paramètre",
    "parametres": "paramètres",
    "procedure": "procédure",
    "procedures": "procédures",
    "repartition": "répartition",
    "role": "rôle",
    "roles": "rôles",
    "securite": "sécurité",
    "selectionne": "sélectionné",
    "specifique": "spécifique",
    "systeme": "système",
    "utilisateur": "utilisateur",
    "verifie": "vérifié",
    "verifier": "vérifier",
    "verification": "vérification",
    "volumineux": "volumineux",
    "acces": "accès",
    "accede": "accède",
    "acquise": "acquise",
    "adresse": "adresse",
    "affichee": "affichée",
    "affiches": "affichés",
    "ajoute": "ajoute",
    "allume": "allumé",
    "annonce": "annoncé",
    "apercu": "aperçu",
    "appareil": "appareil",
    "arrivee": "arrivée",
    "attribue": "attribué",
    "autorisee": "autorisée",
    "autorise": "autorisé",
    "comportement": "comportement",
    "concernee": "concernée",
    "consideree": "considérée",
    "construit": "construit",
    "contient": "contient",
    "defini": "défini",
    "definition": "définition",
    "delivre": "délivre",
    "demandee": "demandée",
    "derniere": "dernière",
    "desactive": "désactivé",
    "detaillee": "détaillée",
    "determine": "déterminé",
    "different": "différent",
    "differente": "différente",
    "distinctes": "distinctes",
    "donneees": "données",
    "empeche": "empêche",
    "emplace": "emplacé",
    "enoncee": "énoncée",
    "enregistre": "enregistré",
    "enregistree": "enregistrée",
    "enregistrees": "enregistrées",
    "etiquette": "étiquette",
    "etiquettes": "étiquettes",
    "evenement": "événement",
    "evenements": "événements",
    "etat": "état",
    "etats": "états",
    "exhaustive": "exhaustive",
    "explicitement": "explicitement",
    "factice": "factice",
    "fermee": "fermée",
    "ferme": "fermé",
    "fige": "figé",
    "generee": "générée",
    "genere": "généré",
    "gerer": "gérer",
    "geres": "gérés",
    "hopital": "hôpital",
    "identifiee": "identifiée",
    "immediate": "immédiate",
    "immediatement": "immédiatement",
    "implique": "implique",
    "inaltere": "inaltéré",
    "inchange": "inchangé",
    "inchangee": "inchangée",
    "incoherent": "incohérent",
    "indexe": "indexé",
    "indexee": "indexée",
    "indexees": "indexées",
    "integree": "intégrée",
    "interroge": "interrogé",
    "introduit": "introduit",
    "liste": "liste",
    "majore": "majoré",
    "mesuree": "mesurée",
    "mesures": "mesures",
    "modelise": "modélisé",
    "modifie": "modifié",
    "modifiee": "modifiée",
    "modifiees": "modifiées",
    "montant": "montant",
    "necessaire": "nécessaire",
    "necessaires": "nécessaires",
    "nommee": "nommée",
    "operateur": "opérateur",
    "operation": "opération",
    "operations": "opérations",
    "operee": "opérée",
    "ordonnancee": "ordonnancée",
    "prealable": "préalable",
    "precisee": "précisée",
    "precisement": "précisément",
    "prepare": "préparé",
    "produite": "produite",
    "propose": "proposé",
    "proposee": "proposée",
    "proposees": "proposées",
    "publie": "publié",
    "publiee": "publiée",
    "reagit": "réagit",
    "reel": "réel",
    "reelle": "réelle",
    "reelles": "réelles",
    "referentiel": "référentiel",
    "referentiels": "référentiels",
    "reinitialise": "réinitialisé",
    "remise": "remise",
    "renseigne": "renseigné",
    "renseignee": "renseignée",
    "renseignes": "renseignés",
    "repete": "répété",
    "represente": "représente",
    "reserve": "réservé",
    "reservee": "réservée",
    "resumee": "résumée",
    "retire": "retiré",
    "reutilisable": "réutilisable",
    "revele": "révèle",
    "saute": "saute",
    "separee": "séparée",
    "separees": "séparées",
    "separement": "séparément",
    "sequence": "séquence",
    "signalee": "signalée",
    "signalees": "signalées",
    "specifiques": "spécifiques",
    "stockee": "stockée",
    "stockees": "stockées",
    "supprime": "supprimé",
    "supprimee": "supprimée",
    "tenue": "tenue",
    "tiree": "tirée",
    "tolerant": "tolérant",
    "tolerante": "tolérante",
    "tracee": "tracée",
    "tracees": "tracées",
    "tronquee": "tronquée",
    "utilise": "utilisé",
    "utilisee": "utilisée",
    "utilisees": "utilisées",
    "verifiee": "vérifiée",
    "verifications": "vérifications",
    "vide": "vide",
    "vise": "visé",
    "visee": "visée",
    "echec": "échec",
    "echecs": "échecs",
    "echoue": "échoué",
    "echouee": "échouée",
    "economise": "économisé",
    "economises": "économisés",
    "eleve": "élevé",
    "elevee": "élevée",
    "enonce": "énoncé",
    "entree": "entrée",
    "entrees": "entrées",
    "etre": "être",
    "evite": "évité",
    "evitee": "évitée",
    "facon": "façon",
    "hopitaux": "hôpitaux",
    "identifie": "identifié",
    "integrite": "intégrité",
    "interet": "intérêt",
    "maitrise": "maîtrise",
    "maitris": "maîtris",
    "meme": "même",
    "memes": "mêmes",
    "applique": "appliqué",
    "appliquee": "appliquée",
    "appliquees": "appliquées",
    "registre": "registre",
    "modele": "modèle",
    "modeles": "modèles",
    "obedir": "obéir",
    "particulierement": "particulièrement",
    "pensee": "pensée",
    "periode": "période",
    "personnalise": "personnalisé",
    "piece": "pièce",
    "pieces": "pièces",
    "piege": "piège",
    "piegeux": "piégeux",
    "precis": "précis",
    "precise": "précise",
    "precision": "précision",
    "precedent": "précédent",
    "precedente": "précédente",
    "presence": "présence",
    "present": "présent",
    "presente": "présente",
    "presentes": "présentes",
    "presentation": "présentation",
    "probleme": "problème",
    "problemes": "problèmes",
    "projet": "projet",
    "qualite": "qualité",
    "realise": "réalisé",
    "realisee": "réalisée",
    "receptionne": "réceptionné",
    "recu": "reçu",
    "recue": "reçue",
    "recues": "reçues",
    "reference": "référence",
    "rejete": "rejeté",
    "rejetee": "rejetée",
    "rejetees": "rejetées",
    "rembourse": "remboursé",
    "remboursee": "remboursée",
    "rembourses": "remboursés",
    "remontee": "remontée",
    "reparties": "réparties",
    "repondu": "répondu",
    "reponse": "réponse",
    "reponses": "réponses",
    "repondre": "répondre",
    "reportees": "reportées",
    "reseau": "réseau",
    "reseaux": "réseaux",
    "resolu": "résolu",
    "resultat": "résultat",
    "resultats": "résultats",
    "sante": "santé",
    "secretaire": "secrétaire",
    "selectionnee": "sélectionnée",
    "selectionnes": "sélectionnés",
    "separes": "séparés",
    "succes": "succès",
    "systemes": "systèmes",
    "telle": "telle",
    "traitee": "traitée",
    "traitees": "traitées",
    "valide": "validé",
    "validee": "validée",
}

#: Expressions multi-mots : l'accentuation de « a » depend du contexte.
EXPRESSIONS: list[tuple[str, str]] = [
    ("a partir", "à partir"),
    ("a l'echec", "à l'échec"),
    ("a lissue", "à l'issue"),
    ("jusqu'a", "jusqu'à"),
    ("d'un cote", "d'un côté"),
    ("de l'autre", "de l'autre"),
]

#: Attributs JSX dont la valeur est du TEXTE affiche.
ATTRIBUTS_TEXTE = {"label", "aide", "placeholder", "title", "alt", "aria-label"}

#: Attributs et expressions dont la valeur est TECHNIQUE : elle ne doit
#: jamais etre accentuee (classe CSS, identifiant, route, cle d'API).
#: On les protege avant la passe, puis on les restaure a l'identique.
TECHNIQUES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"className=\{[^{}]*\}"), "className"),
    (re.compile(r"className=\"[^\"]*\""), "className"),
    (re.compile(r"\bclass=\"[^\"]*\""), "class"),
    (re.compile(r"\bid=\"[^\"]*\""), "id"),
    (re.compile(r"\bhtmlFor=\"[^\"]*\""), "htmlFor"),
    (re.compile(r"\bname=\"[^\"]*\""), "name"),
    (re.compile(r"\btype=\"[^\"]*\""), "type"),
    (re.compile(r"\brole=\"[^\"]*\""), "role"),
    (re.compile(r"\bhref=\"[^\"]*\""), "href"),
    (re.compile(r"\bto=\"[^\"]*\""), "to"),
    (re.compile(r"\bsrc=\"[^\"]*\""), "src"),
    (re.compile(r"\bkey=\"[^\"]*\""), "key"),
    (re.compile(r"\baria-[a-z]+=\"[^\"]*\""), "aria"),
    (re.compile(r"\bdata-[a-z-]+=\"[^\"]*\""), "data"),
]

#: Litteral compare a une valeur de code (`onglet === 'sante'`). Ce sont
#: des CLES, pas des textes : les accentuer casserait la correspondance.
#: On les repere dans le fichier avant la passe.
COMPARAISON = re.compile(r"(?:===|!==|==)\s*('[^']*'|\"[^\"]*\")")

#: Valeurs techniques connues, protegees meme sans comparaison visible.
VALEURS_TECHNIQUES = {
    "seuil",
    "modele",
    "sante",
    "observabilite",
    "canaux",
    "utilisateurs",
    "audit",
    "file",
    "historique",
    "decision",
    "alerte",
    "alertes",
    "facture",
    "factures",
    "ordonnance",
    "ordonnances",
    "prediction",
    "assure",
    "gestionnaire",
    "administrateur",
    "professionnel_sante",
    "ok",
    "ko",
    "neutre",
    "info",
    "succes",
    "erreur",
    "avert",
    "utilisateur",
    "compte",
    "comptes",
    "paiement",
    "remboursement",
    "reference",
    "references",
    "montant",
    "score",
    "detail",
    "details",
    "page",
    "ligne",
    "lignes",
    "total",
    "acte",
    "actes",
}

#: Caracteres qui signalent une valeur technique (cle d'API, URL, classe).
TECHNIQUE = re.compile(r"[_/\\{}$=():;,<>@#]")

#: Litteral de chaine (simples, doubles, backticks).
CHAINE = re.compile(r"('(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`)", re.S)

#: Attribut JSX : nom="valeur".
ATTRIBUT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*=\s*(\"(?:[^\"\\\n]|\\.)*\")")

#: Texte JSX entre `>` et `<`.
#: Sur UNE SEULE LIGNE, et sans caractere de code : sinon la regex
#: traverserait une expression TypeScript (`useState<string | null>(null)`
#: ...) et accentuerait des IDENTIFIANTS.
TEXTE_JSX = re.compile(r">([^<>{}()\[\];=|&?!*`\"'/\\\n]{2,300})<")

#: Mots deja accentues ou sans accent : on ne touche pas au "a" isole
#: (verbe avoir) ni aux mots anglais.
MOT_SEUL = re.compile(r"[A-Za-zÀ-ÿ]+")


def _accentuer_mot(mot: str) -> str:
    """Accentue un mot, quelle que soit sa casse initiale.

    « Donnees » doit devenir « Données » : la recherche se fait sur la
    forme minuscule, et la casse de la initiale est conservee.
    """
    if mot in DICTIONNAIRE:
        return DICTIONNAIRE[mot]
    minuscule = mot.lower()
    if minuscule in DICTIONNAIRE:
        accentue = DICTIONNAIRE[minuscule]
        return accentue[0].upper() + accentue[1:]
    return mot


def accentuer(texte: str) -> str:
    """Applique le dictionnaire a un texte affichable."""
    for avant, apres in EXPRESSIONS:
        texte = re.sub(rf"\b{re.escape(avant)}\b", apres, texte, flags=re.IGNORECASE)
    return MOT_SEUL.sub(lambda m: _accentuer_mot(m.group(0)), texte)


def _est_technique(contenu: str) -> bool:
    """Vrai si la chaine ressemble a une valeur technique et non a un texte."""
    return bool(TECHNIQUE.search(contenu))


def _accentuer_chaine(litteral: str) -> str:
    """Accentue l'interieur d'un litteral, sauf s'il est technique."""
    guillemet = litteral[0]
    interieur = litteral[1:-1]
    if _est_technique(interieur):
        return litteral
    return guillemet + accentuer(interieur) + guillemet


def traiter_fichier(chemin: Path, verifier: bool) -> tuple[str, int]:
    """Accentue un fichier. Rend (contenu, nombre de remplacements)."""
    original = chemin.read_text(encoding="utf-8")
    compte = 0

    # --- 0. Valeurs techniques a ne JAMAIS toucher ------------------------
    # Un litteral compare a une valeur de code est une CLE, pas un texte.
    # Accentuer une cle casse silencieusement la correspondance.
    proteges: list[str] = []
    cles: set[str] = set()

    def _proteger(m: re.Match[str]) -> str:
        proteges.append(m.group(0))
        return f"\x00PROTEGE{len(proteges) - 1}\x00"

    contenu = original
    for motif, _nom in TECHNIQUES:
        contenu = motif.sub(_proteger, contenu)

    for m in COMPARAISON.finditer(contenu):
        litteral = m.group(1)
        cles.add(litteral[1:-1])
    for m in CHAINE.finditer(contenu):
        litteral = m.group(0)
        interieur = litteral[1:-1]
        if interieur in VALEURS_TECHNIQUES:
            cles.add(interieur)

    def _proteger_cle(m: re.Match[str]) -> str:
        litteral = m.group(0)
        if litteral[1:-1] in cles:
            return _proteger(m)
        return litteral

    contenu = CHAINE.sub(_proteger_cle, contenu)

    # --- 1. Texte JSX --------------------------------------------------
    def _texte(m: re.Match[str]) -> str:
        nonlocal compte
        nouveau = accentuer(m.group(1))
        if nouveau != m.group(1):
            compte += 1
        return ">" + nouveau + "<"

    contenu = TEXTE_JSX.sub(_texte, contenu)

    # --- 2. Attributs textuels ------------------------------------------
    def _attribut(m: re.Match[str]) -> str:
        nonlocal compte
        nom, valeur = m.group(1), m.group(2)
        if nom.lower() not in ATTRIBUTS_TEXTE:
            return m.group(0)
        interieur = valeur[1:-1]
        if _est_technique(interieur) or interieur in cles:
            return m.group(0)
        nouveau = accentuer(interieur)
        if nouveau != interieur:
            compte += 1
        return f'{nom}="{nouveau}"'

    contenu = ATTRIBUT.sub(_attribut, contenu)

    # --- 3. Litteraux de chaine restants ---------------------------------
    def _chaine(m: re.Match[str]) -> str:
        nonlocal compte
        litteral = m.group(0)
        if "${" in litteral or "\\n" in litteral:
            return litteral
        if litteral[1:-1] in cles:
            return litteral
        nouveau = _accentuer_chaine(litteral)
        if nouveau != litteral:
            compte += 1
        return nouveau

    contenu = CHAINE.sub(_chaine, contenu)

    # --- 4. Restauration des valeurs techniques --------------------------
    for index, valeur in enumerate(proteges):
        contenu = contenu.replace(f"\x00PROTEGE{index}\x00", valeur)

    if verifier:
        return contenu, compte
    if contenu != original:
        chemin.write_text(contenu, encoding="utf-8", newline="\n")
    return contenu, compte


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--verifier", action="store_true", help="ne rien ecrire")
    arguments = parseur.parse_args()

    total = 0
    for chemin in sorted(RACINE.rglob("*.ts*")):
        _contenu, compte = traiter_fichier(chemin, arguments.verifier)
        total += compte
        if compte > 0 and not arguments.verifier:
            print(f"{chemin.relative_to(RACINE.parent.parent)} : {compte} bloc(s)")
    print(f"Total : {total} bloc(s) accentuable(s).")
    # En mode verificateur, le code de sortie DOIT refleter le constat : un
    # verificateur qui renvoie toujours 0 ne verifie rien.
    return 1 if (arguments.verifier and total) else 0


if __name__ == "__main__":
    sys.exit(main())
