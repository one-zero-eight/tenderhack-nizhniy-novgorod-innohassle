import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/cn'
import type { ManualSection } from '@/lib/knowledge-api'

interface KnowledgeSidebarProps {
  slug: string
  sections: ManualSection[]
  activeSectionId?: string
  className?: string
}

/**
 * Table of contents for a manual. Sections arrive as a flat list with a
 * `depth`, so nesting is expressed through indentation and font weight.
 */
export default function KnowledgeSidebar({ slug, sections, activeSectionId, className }: KnowledgeSidebarProps) {
  return (
    <nav className={cn('flex flex-col gap-0.5 text-sm', className)} aria-label="Содержание руководства">
      {sections.map((section) => {
        const isActive = section.id === activeSectionId
        return (
          <Link
            key={section.id}
            to="/knowledge-base/$slug/$sectionId"
            params={{ slug, sectionId: section.id }}
            className={cn(
              'rounded px-2 py-1 no-underline transition-colors',
              // Indent by nesting depth, capped so deep ids stay readable.
              section.depth === 0 ? 'font-semibold' : undefined,
              isActive ? 'bg-main-blue/10 text-main-blue' : 'text-black hover:bg-pale-blue/50 hover:text-main-blue',
            )}
            style={{ paddingLeft: `${0.5 + Math.min(section.depth, 5) * 0.75}rem` }}
            title={section.title_line}
          >
            <span className="line-clamp-2">{section.title_line}</span>
          </Link>
        )
      })}
    </nav>
  )
}
