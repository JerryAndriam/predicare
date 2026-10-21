import { useNavigate } from 'react-router-dom'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  ChevronDown,
  ChevronRight,
  CircleHelp,
  KeyRound,
  LifeBuoy,
  LogOut,
  User,
} from 'lucide-react'

const item =
  'flex w-full cursor-pointer select-none items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-soft outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/30 data-[highlighted]:bg-surface-2 data-[highlighted]:text-ink'
const sousItem =
  'flex w-full cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-soft outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/30 data-[highlighted]:bg-primary-soft data-[highlighted]:text-primary-dark'

export function MenuProfil({
  nom,
  role,
  initiales,
  onSortie,
}: {
  nom: string
  role: string
  initiales: string
  onSortie: () => void
}) {
  const navigate = useNavigate()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label="Menu du profil"
          className="flex h-10 items-center gap-2 rounded-full border border-line bg-transparent pl-1 pr-3 text-ink-soft outline-none transition-colors hover:border-line-strong hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-primary/30 data-[state=open]:border-line-strong data-[state=open]:bg-surface-2"
        >
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-primary-soft text-[13px] font-bold text-primary-dark">
            {initiales}
          </span>
          <span className="hidden max-w-[14ch] truncate text-[13px] font-semibold text-ink sm:inline">
            {nom}
          </span>
          <ChevronDown size={16} aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-[60] min-w-[264px] animate-menu rounded-card border border-line bg-surface p-2 shadow-card"
        >
          <div className="mb-1 border-b border-line px-3 pb-3 pt-2">
            <p className="truncate font-display text-sm font-semibold text-ink">{nom}</p>
            <p className="text-xs text-ink-muted">{role}</p>
          </div>

          <DropdownMenu.Sub>
            <DropdownMenu.SubTrigger className={item}>
              <User size={16} aria-hidden="true" />
              Mon compte
              <ChevronRight size={15} className="ml-auto text-ink-muted" aria-hidden="true" />
            </DropdownMenu.SubTrigger>
            <DropdownMenu.Portal>
              <DropdownMenu.SubContent
                sideOffset={6}
                className="z-[60] min-w-[190px] animate-menu rounded-card border border-line bg-surface p-1.5 shadow-card"
              >
                <DropdownMenu.Item className={sousItem} onSelect={() => navigate('/compte#profil')}>
                  Profil
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  className={sousItem}
                  onSelect={() => navigate('/compte#mot-de-passe')}
                >
                  <KeyRound size={15} aria-hidden="true" />
                  Mot de passe
                </DropdownMenu.Item>
              </DropdownMenu.SubContent>
            </DropdownMenu.Portal>
          </DropdownMenu.Sub>

          <DropdownMenu.Sub>
            <DropdownMenu.SubTrigger className={item}>
              <CircleHelp size={16} aria-hidden="true" />
              Aide
              <ChevronRight size={15} className="ml-auto text-ink-muted" aria-hidden="true" />
            </DropdownMenu.SubTrigger>
            <DropdownMenu.Portal>
              <DropdownMenu.SubContent
                sideOffset={6}
                className="z-[60] min-w-[210px] animate-menu rounded-card border border-line bg-surface p-1.5 shadow-card"
              >
                <DropdownMenu.Item className={sousItem} onSelect={() => navigate('/aide#faq')}>
                  Questions fréquentes
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  className={sousItem}
                  onSelect={() => navigate('/aide#procedures')}
                >
                  Procédures
                </DropdownMenu.Item>
                <DropdownMenu.Item className={sousItem} onSelect={() => navigate('/aide')}>
                  <LifeBuoy size={15} aria-hidden="true" />
                  Centre d’aide
                </DropdownMenu.Item>
              </DropdownMenu.SubContent>
            </DropdownMenu.Portal>
          </DropdownMenu.Sub>

          <DropdownMenu.Separator className="my-1 h-px bg-line" />

          <DropdownMenu.Item
            className="flex w-full cursor-pointer select-none items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-danger outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/30 data-[highlighted]:bg-[#faece9]"
            onSelect={onSortie}
          >
            <LogOut size={16} aria-hidden="true" />
            Se déconnecter
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
