import { useState, type ReactNode } from 'react'
import { FaChevronDown } from 'react-icons/fa6'
import { cn } from '@/lib/cn'

interface DisclosureProps {
  title: ReactNode
  /** Optional content shown to the right of the title (e.g. a count). */
  meta?: ReactNode
  /** Whether the section starts expanded. */
  defaultOpen?: boolean
  /** Nesting level, used to indent nested disclosures. */
  level?: number
  children: ReactNode
  className?: string
}

/**
 * Minimal collapsible section with a chevron that rotates when expanded.
 * Nested disclosures drop their outer border so the tree reads as one panel.
 */
export default function Disclosure({ title, meta, defaultOpen = false, level = 0, children, className }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={cn('border-gray-blue', level === 0 ? 'border' : 'border-0 border-t', className)}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={cn(
          'hover:bg-pale-blue/50 flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
          'border-gray-blue',
          open ? 'border-b' : 'border-b-0',
        )}
        style={{ paddingLeft: `${1 + level * 1.25}rem` }}
      >
        <FaChevronDown className={cn('text-gray size-3 shrink-0 transition-transform', open ? undefined : '-rotate-90')} />
        <span className="text-black min-w-0 flex-1 truncate font-medium">{title}</span>
        {meta}
      </button>
      {open && <div>{children}</div>}
    </div>
  )
}
