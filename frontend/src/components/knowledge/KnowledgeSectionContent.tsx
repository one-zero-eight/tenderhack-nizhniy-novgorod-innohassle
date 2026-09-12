import { cn } from '@/lib/cn'
import type { SectionContent } from '@/lib/knowledge-api'

interface KnowledgeSectionContentProps {
  section: SectionContent
  className?: string
}

/**
 * Renders a knowledge-base section: breadcrumbs, heading, and body.
 *
 * The backend returns `content` as plain text with paragraphs separated by
 * blank lines, so it is split rather than parsed as Markdown.
 */
export default function KnowledgeSectionContent({ section, className }: KnowledgeSectionContentProps) {
  const paragraphs = section.content
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)

  return (
    <article className={cn('flex flex-col gap-4', className)}>
      {section.breadcrumbs.length > 0 && (
        <nav className="text-gray flex flex-wrap items-center gap-1 text-xs" aria-label="Хлебные крошки">
          {section.breadcrumbs.map((crumb, index) => (
            <span key={`${crumb}-${index}`} className="flex items-center gap-1">
              {index > 0 && <span aria-hidden="true">/</span>}
              <span className={index === section.breadcrumbs.length - 1 ? 'text-pale-black' : undefined}>{crumb}</span>
            </span>
          ))}
        </nav>
      )}

      <h1 className="text-pale-black text-2xl font-bold">{section.title_line}</h1>

      {paragraphs.length === 0 ? (
        <p className="text-gray text-sm">В этом разделе нет содержимого.</p>
      ) : (
        <div className="text-pale-black flex flex-col gap-3 text-sm leading-relaxed">
          {paragraphs.map((paragraph, index) => (
            <p key={index} className="whitespace-pre-wrap">
              {paragraph}
            </p>
          ))}
        </div>
      )}
    </article>
  )
}
