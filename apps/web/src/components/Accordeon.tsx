import type { ReactNode } from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import { ChevronDown } from 'lucide-react'

export interface ElementAccordeon {
  valeur: string
  titre: string
  contenu: ReactNode
}

export function Accordeon({
  elements,
  defaut,
}: {
  elements: ElementAccordeon[]
  defaut?: string
}) {
  return (
    <Accordion.Root
      type="single"
      collapsible
      defaultValue={defaut}
      className="divide-y divide-line overflow-hidden rounded-card border border-line bg-surface"
    >
      {elements.map((element) => (
        <Accordion.Item value={element.valeur} key={element.valeur} className="group">
          <Accordion.Header>
            <Accordion.Trigger className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left font-display text-[15px] font-semibold text-ink outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/30 data-[state=open]:text-primary-dark">
              {element.titre}
              <ChevronDown
                size={18}
                aria-hidden="true"
                className="shrink-0 text-ink-muted transition-transform duration-200 group-data-[state=open]:rotate-180"
              />
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content className="px-5 pb-5 text-[15px] leading-relaxed text-ink-soft">
            {element.contenu}
          </Accordion.Content>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  )
}
