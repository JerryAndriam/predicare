import { embedDashboard } from "@superset-ui/embedded-sdk";
import { useEffect, useRef, useState } from "react";

import { api, messageErreur } from "../api/client";
import type { GuestTokenResponse } from "../api/types";
import { EnTetePage } from "../components/blocs";
import { Carte, Chargement, EtatVide } from "../components/ui";

const URL_SUPERSET = (
  import.meta.env.VITE_SUPERSET_URL || "http://localhost:8088"
).replace(/\/$/, "");

/**
 * Tableau de bord BI, integre a l'application.
 *
 * Le tableau Superset est affiche dans une iframe de MEME ORIGINE : la
 * passerelle route `/bi` et les chemins absolus de Superset (`/static`,
 * `/api/v1`, `/embedded`, `/superset`) vers le service BI. Aucune derogation
 * CSP vers un tiers n'est donc necessaire.
 *
 * L'authentification ne demande pas de seconde connexion : api-core demande
 * un guest token court a Superset avec un compte de service, et le SDK le
 * renouvelle automatiquement. Le mot de passe Superset ne quitte jamais le
 * serveur.
 */
export function PilotagePage() {
  const [etat, setEtat] = useState<"chargement" | "ok" | "indisponible">(
    "chargement",
  );
  const [erreur, setErreur] = useState<string | null>(null);
  const [tentative, setTentative] = useState(0);
  const conteneur = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let annule = false;
    let tableau: { unmount: () => void } | undefined;

    const charger = async () => {
      setEtat("chargement");
      setErreur(null);
      try {
        const { token, dashboard_uuid } = await api<GuestTokenResponse>(
          "/api/core/pilotage/guest-token",
          { method: "POST" },
        );
        if (annule || !conteneur.current) return;

        // Le SDK demande le token au moment de monter l'iframe. On reutilise
        // le token deja obtenu pour le premier affichage, puis on en redemande
        // un a l'expiration (5 min).
        let premierJeton: string | null = token;
        tableau = await embedDashboard({
          id: dashboard_uuid,
          supersetDomain: window.location.origin,
          mountPoint: conteneur.current,
          fetchGuestToken: async () => {
            if (premierJeton) {
              const valeur = premierJeton;
              premierJeton = null;
              return valeur;
            }
            const rafraichi = await api<GuestTokenResponse>(
              "/api/core/pilotage/guest-token",
              { method: "POST" },
            );
            return rafraichi.token;
          },
          dashboardUiConfig: {
            hideTitle: true,
            hideTab: true,
          },
        });

        if (annule) {
          tableau.unmount();
          return;
        }
        setEtat("ok");
      } catch (probleme) {
        if (!annule) {
          setErreur(messageErreur(probleme));
          setEtat("indisponible");
        }
      }
    };

    void charger();
    return () => {
      annule = true;
      try {
        tableau?.unmount();
      } catch {
        // Le SDK peut deja avoir demonte l'iframe : rien a faire.
      }
    };
  }, [tentative]);

  return (
    <div className="pile">
      <EnTetePage
        fil={[{ libelle: "Pilotage décisionnel" }]}
        titre="Pilotage décisionnel"
        chapo={
          <>
            Le tableau de bord Superset est branché en lecture seule sur la base
            : il montre le volume de factures, la fraude détectée, le cycle de
            décision et les meilleurs prestataires. Il est servi par la même
            passerelle que l’application, sans seconde connexion à ouvrir. Le
            menu « … » d’une tuile ouvre sa requête, ses données, son export ou
            le détail des lignes.
          </>
        }
      />

      {etat === "chargement" && (
        <Chargement texte="Préparation du tableau de bord…" />
      )}

      {etat === "indisponible" && (
        <Carte titre="Tableau de bord indisponible">
          <EtatVide
            titre="Le tableau de bord n’a pas pu être chargé"
            texte={`${erreur ?? "Le tableau de bord est indisponible."} Lancez « make up-bi » pour démarrer le profil BI, puis rechargez cette page.`}
            action={
              <button
                className="bouton principal"
                type="button"
                onClick={() => {
                  setEtat("chargement");
                  setTentative((valeur) => valeur + 1);
                }}
              >
                Réessayer
              </button>
            }
          />
        </Carte>
      )}

      {etat !== "indisponible" && (
        <Carte
          titre="Tableau de bord"
          actions={
            <a className="lien" href={`${URL_SUPERSET}/chart/list/`}>
              Ouvrir Superset
            </a>
          }
        >
          <div
            ref={conteneur}
            className="bi-frame"
            title="Tableau de bord décisionnel KolikolyCare"
          />
        </Carte>
      )}
    </div>
  );
}
