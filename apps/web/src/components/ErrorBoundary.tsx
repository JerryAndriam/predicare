import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Etat {
  erreur: Error | null
}

/**
 * Filet de securite de l'interface.
 *
 * Sans lui, une erreur de rendu React vide l'ecran entier : l'utilisateur
 * voit une page blanche, sans moyen de revenir, et l'exploitant n'a ni
 * message ni trace exploitable. Ici, l'ecran affiche un message et un
 * bouton qui recharge l'application.
 *
 * Le journal reste dans la console du navigateur : c'est la que le
 * developpeur regarde. Le message, lui, parle a l'utilisateur.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, Etat> {
  state: Etat = { erreur: null }

  static getDerivedStateFromError(erreur: Error): Etat {
    return { erreur }
  }

  componentDidCatch(erreur: Error, infos: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('Erreur de rendu React', erreur, infos.componentStack)
  }

  render(): ReactNode {
    const { erreur } = this.state
    if (erreur === null) return this.props.children

    return (
      <div className="erreur-ecran" role="alert">
        <h1>Une erreur est survenue</h1>
        <p>
          L’interface n’a pas pu s’afficher. Les données ne sont pas perdues : rechargez
          simplement la page pour reprendre votre session.
        </p>
        <p className="mono aide">{erreur.message}</p>
        <button type="button" className="bouton principal" onClick={() => window.location.reload()}>
          Recharger la page
        </button>
      </div>
    )
  }
}
