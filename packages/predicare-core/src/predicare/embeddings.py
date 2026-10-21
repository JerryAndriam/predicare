"""Représentation vectorielle des textes, calculable sans aucun fournisseur.

Pourquoi ce module existe
-------------------------
Le cahier des charges veut un assistant documentaire qui cite ses sources, et
une exigence de souveraineté impose que les contrats ne quittent jamais la
machine. Or les embeddings semantiques usuels (OpenAI, sentence-transformers)
sont soit des services distants, soit des modeles a charger.

Ce module fournit une **troisieme voie** : une empreinte lexicale, c'est-a-dire
une projection stable des mots (et des paires de mots) dans un vecteur de
dimension fixee. Elle ne "comprend" pas le texte : elle le *note*. Deux
questions qui partagent les memes mots obtiennent des vecteurs proches ; deux
questions formulees differemment avec les memes mots aussi, ce qui n'est pas le
cas d'une simple recherche par mots-cles.

Ce n'est donc ni un embedder semantique, ni un remplacant : c'est le **filet**
qui garantit que la demonstration fonctionne sans cle, sans reseau et sans
cout. Le choix se fait par configuration :

* `EMBEDDING_MODE=semantic` : le fournisseur de l'environnement ;
* `EMBEDDING_MODE=empreinte` : le calcul local, toujours ;
* `EMBEDDING_MODE=auto` (defaut) : le fournisseur s'il est configure, sinon
  l'empreinte.

Deux proprietes non negociables
--------------------------------
1. **Le hachage est stable entre les processus.** `hash()` de Python est
   randomise a chaque demarrage : le vecteur de l'index et celui de la
   question seraient dans deux espaces differents, et la similarite
   ramenerait n'importe quoi. On passe donc par `blake2b`.
2. **L'espace vectoriel est identifie.** La colonne `modele_embedding`
   enregistre quel calculateur a produit les vecteurs : interroger un index
   construit par un autre calculateur doit le dire, pas produire une erreur
   de vecteur illisible.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

#: Nom de l'espace vectoriel produit par l'empreinte lexicale. Il est ecrit
#: dans `core.document_vectorise.modele_embedding` : l'index dit ainsi, sans
#: ambiguite, avec quoi il a ete construit.
NOM_EMPREINTE = "empreinte-lexicale-v1"

#: Mots vides francais. Ils portent la grammaire, pas le sens : les retirer
#: evite que « le » et « de » consomment la place d'un mot qui porte
#: l'information, dans un vecteur de dimension fixee.
MOTS_VIDES: frozenset[str] = frozenset(
    [
        "a",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "en",
        "et",
        "eux",
        "il",
        "je",
        "la",
        "le",
        "les",
        "leur",
        "lui",
        "ma",
        "mais",
        "me",
        "meme",
        "mes",
        "moi",
        "mon",
        "ne",
        "nos",
        "notre",
        "nous",
        "on",
        "ou",
        "par",
        "pas",
        "pour",
        "qu",
        "que",
        "qui",
        "sa",
        "se",
        "ses",
        "son",
        "sur",
        "ta",
        "te",
        "tes",
        "toi",
        "ton",
        "tu",
        "un",
        "une",
        "vos",
        "votre",
        "vous",
        "c",
        "d",
        "j",
        "l",
        "m",
        "n",
        "s",
        "t",
        "y",
        "ete",
        "etee",
        "etees",
        "etes",
        "etant",
        "suis",
        "es",
        "est",
        "sommes",
        "etes",
        "sont",
        "sera",
        "seront",
    ]
)


class Embedder(Protocol):
    """Le contrat minimal dont dependent l'indexation et la recherche."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normaliser(texte: str) -> str:
    """Minuscules, sans accent, ponctuation ramenee a l'espace."""
    sans_accent = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texte.lower())
        if unicodedata.category(caractere) != "Mn"
    )
    return "".join(c if c.isalnum() else " " for c in sans_accent)


def _jetons(texte: str) -> list[str]:
    mots = [mot for mot in _normaliser(texte).split() if mot and mot not in MOTS_VIDES]
    if len(mots) < 2:
        return mots
    # Les paires de mots adjacents : « plafond annuel » et « annuel plafond »
    # ne se ressemblent pas, mais « plafond annuel » et « plafond de rembourse-
    # ment annuel » partagent la paire « plafond annuel ». C'est ce qui
    # distingue cette empreinte d'une simple recherche par mots-cles.
    paires = [f"{a}_{b}" for a, b in itertools.pairwise(mots)]
    return mots + paires


def _hachages(mot: str) -> tuple[int, int]:
    """Deux empreintes stables : la position dans le vecteur, et son signe.

    Le signe aleatoire (ici derive d'une seconde empreinte) evite que les
    collisions ne s'additionnent toujours dans le meme sens : c'est le
    « hashing trick » signe.
    """
    premiere = hashlib.blake2b(mot.encode("utf-8"), digest_size=8).digest()
    seconde = hashlib.blake2b(mot.encode("utf-8"), digest_size=8, salt=b"signe").digest()
    return (
        int.from_bytes(premiere, "big") % 1_000_000_007,
        1 if seconde[0] & 1 else -1,
    )


class EmpreinteLexicale:
    """Projection lexicale stable dans un vecteur de dimension fixee.

    La ponderation est un `tf` sous-lineaire (`1 + log(tf)`) : un mot
    repete dix fois ne pese pas dix fois plus. Le vecteur est normalise, ce
    qui rend la similarite cosinus independante de la longueur du texte.
    """

    def __init__(self, dimension: int = 1536) -> None:
        if dimension <= 0:
            raise ValueError("La dimension du vecteur doit etre positive.")
        self.dimension = dimension
        self.nom_modele = NOM_EMPREINTE

    def _vecteur(self, texte: str) -> list[float]:
        vecteur = [0.0] * self.dimension
        compte: dict[str, int] = {}
        for mot in _jetons(texte):
            compte[mot] = compte.get(mot, 0) + 1
        for mot, frequence in compte.items():
            position, signe = _hachages(mot)
            index = position % self.dimension
            poids = (1.0 + math.log(frequence)) * signe
            vecteur[index] += poids
        norme = math.sqrt(sum(valeur * valeur for valeur in vecteur))
        if norme == 0.0:
            # Aucun mot connu : le vecteur est nul, et une similarite
            # cosinus avec un vecteur nul n'a pas de sens. On laisse le
            # vecteur nul et l'appelant decide (recherche lexicale).
            return vecteur
        return [valeur / norme for valeur in vecteur]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vecteur(texte) for texte in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vecteur(text)


def secret_utilisable(valeur: str) -> bool:
    """Vrai si la valeur ressemble a une vraie cle, pas a un gabarit."""
    if not valeur or not valeur.strip():
        return False
    marqueurs = ("change-me", "changer", "changeme", "not-configured", "votre-cle")
    return not any(marqueur in valeur.lower() for marqueur in marqueurs)


def choisir_embedder(settings: Any) -> Embedder:
    """Choisit le calculateur d'embeddings selon la configuration.

    `auto` (le defaut) privilegie le fournisseur s'il est reellement
    configure, et bascule sur l'empreinte locale sinon. C'est ce qui rend la
    plateforme utilisable sans cle : l'assistant fonctionne, avec une
    recherche lexicale plutot que semantique, et l'ecran le dit.
    """
    mode = (getattr(settings, "embedding_mode", "auto") or "auto").strip().lower()
    if mode not in {"auto", "semantic", "empreinte"}:
        raise RuntimeError(
            f"EMBEDDING_MODE inconnu : {mode!r} (attendu : auto, semantic, empreinte)."
        )

    if mode == "empreinte":
        return EmpreinteLexicale(int(getattr(settings, "embedding_dimension", 1536)))

    if mode == "semantic" or secret_utilisable(getattr(settings, "embedding_api_key", "")):
        try:
            from langchain_openai import OpenAIEmbeddings
            from pydantic import SecretStr
        except ImportError as exc:  # pragma: no cover - dependance absente
            if mode == "semantic":
                raise RuntimeError(
                    "EMBEDDING_MODE=semantic exige le client OpenAI (langchain-openai)."
                ) from exc
        else:
            return OpenAIEmbeddings(
                base_url=getattr(settings, "embedding_api_base", "") or None,
                api_key=SecretStr(getattr(settings, "embedding_api_key", "") or "not-configured"),
                model=getattr(settings, "embedding_model", "text-embedding-3-small"),
            )

    return EmpreinteLexicale(int(getattr(settings, "embedding_dimension", 1536)))


def nom_modele(embedder: Any, settings: Any) -> str:
    """Nom de l'espace vectoriel, pour l'ecrire dans l'index."""
    nom = getattr(embedder, "nom_modele", None)
    if nom:
        return str(nom)
    return str(getattr(settings, "embedding_model", "inconnu"))


def vecteur_nul(vecteur: Sequence[float]) -> bool:
    """Vrai si le vecteur ne porte aucune information (tout a zero)."""
    return not any(abs(valeur) > 1e-12 for valeur in vecteur)


def jetons_significatifs(texte: str, minimum: int = 1) -> list[str]:
    """Jetons retenus pour une recherche lexicale (mots pleins)."""
    return [mot for mot in _jetons(texte) if "_" not in mot][: max(minimum, 0)]


def requete_lexicale(texte: str) -> list[str]:
    """Expression de recherche lexicale : les mots pleins, uniques.

    Sert de filet quand la recherche vectorielle est indisponible : une
    recherche `ILIKE` sur ces mots ne demande aucun fournisseur et trouve
    encore le bon passage, a condition que la question reprenne les mots du
    contrat.
    """
    vus: list[str] = []
    for mot in _jetons(texte):
        if "_" in mot or mot in vus:
            continue
        vus.append(mot)
    return vus[:12]


def embedder_est_local(embedder: Any) -> bool:
    """Vrai si le calculateur ne fait aucun appel reseau."""
    return isinstance(embedder, EmpreinteLexicale)


def jetons_de(embedder: Any) -> Iterable[str]:
    """jetons d'un embedder local (vide pour un fournisseur)."""
    if isinstance(embedder, EmpreinteLexicale):
        return MOTS_VIDES
    return ()
