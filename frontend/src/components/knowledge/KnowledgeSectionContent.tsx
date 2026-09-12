import { Markdown, type MarkdownComponentProps, type MarkdownComponents } from '@tanstack/markdown/react'
import { cn } from '@/lib/cn'
import { prepareManualMarkdown, resolveKnowledgeSrc, type SectionContent } from '@/lib/knowledge-api'

interface KnowledgeSectionContentProps {
  section: SectionContent
  className?: string
}

/** Props passed to custom components; the parser adds a `node` field we drop. */
type ElementProps<Tag extends keyof React.JSX.IntrinsicElements> = MarkdownComponentProps<Tag> & { node?: unknown }

/** Removes the non-DOM `node` prop before spreading onto an element. */
function withoutNode<T extends { node?: unknown }>({ node, ...rest }: T): Omit<T, 'node'> {
  void node
  return rest
}

/**
 * Element styling for manual sections: readable prose with tables and
 * screenshots, aligned with the rest of the knowledge-base layout.
 */
const components = {
  p: (props: ElementProps<'p'>) => <p {...withoutNode(props)} className="mb-3 last:mb-0" />,
  strong: (props: ElementProps<'strong'>) => <strong {...withoutNode(props)} className="font-semibold" />,
  em: (props: ElementProps<'em'>) => <em {...withoutNode(props)} className="italic" />,
  ul: (props: ElementProps<'ul'>) => <ul {...withoutNode(props)} className="mb-3 list-disc space-y-1 pl-5 last:mb-0" />,
  ol: (props: ElementProps<'ol'>) => <ol {...withoutNode(props)} className="mb-3 list-decimal space-y-1 pl-5 last:mb-0" />,
  li: (props: ElementProps<'li'>) => <li {...withoutNode(props)} className="leading-relaxed" />,
  a: (props: ElementProps<'a'>) => (
    <a
      {...withoutNode(props)}
      target="_blank"
      rel="noopener noreferrer"
      className="text-main-blue underline underline-offset-2 hover:text-red"
    />
  ),
  blockquote: (props: ElementProps<'blockquote'>) => (
    <blockquote {...withoutNode(props)} className="border-gray-blue text-pale-black my-3 border-l-[3px] pl-3" />
  ),
  hr: (props: ElementProps<'hr'>) => <hr {...withoutNode(props)} className="border-gray-blue my-4" />,
  h1: (props: ElementProps<'h1'>) => <h2 {...withoutNode(props)} className="mt-5 mb-2 text-base font-bold first:mt-0" />,
  h2: (props: ElementProps<'h2'>) => <h2 {...withoutNode(props)} className="mt-5 mb-2 text-base font-bold first:mt-0" />,
  h3: (props: ElementProps<'h3'>) => <h3 {...withoutNode(props)} className="mt-4 mb-2 text-sm font-bold first:mt-0" />,
  h4: (props: ElementProps<'h4'>) => <h4 {...withoutNode(props)} className="mt-4 mb-2 text-sm font-semibold first:mt-0" />,
  code: (props: ElementProps<'code'>) => {
    const { className, ...rest } = withoutNode(props)
    const block = className?.includes('language-')
    return (
      <code
        {...rest}
        className={cn('font-mono text-[0.85em]', block ? cn('bg-transparent text-inherit', className) : 'bg-pale-blue px-1 py-0.5')}
      />
    )
  },
  pre: (props: ElementProps<'pre'>) => (
    <pre
      {...withoutNode(props)}
      className="border-gray-blue bg-pale-blue text-black my-3 overflow-x-auto whitespace-pre-wrap border p-3 font-mono text-[0.85em] leading-relaxed"
    />
  ),
  table: (props: ElementProps<'table'>) => (
    <div className="my-3 overflow-x-auto">
      <table {...withoutNode(props)} className="w-full border-collapse text-sm" />
    </div>
  ),
  thead: (props: ElementProps<'thead'>) => <thead {...withoutNode(props)} />,
  tbody: (props: ElementProps<'tbody'>) => <tbody {...withoutNode(props)} />,
  tr: (props: ElementProps<'tr'>) => <tr {...withoutNode(props)} />,
  th: (props: ElementProps<'th'>) => (
    <th {...withoutNode(props)} className="border-gray-blue bg-pale-blue border px-2.5 py-1.5 text-left font-bold" />
  ),
  td: (props: ElementProps<'td'>) => (
    <td {...withoutNode(props)} className="border-gray-blue border px-2.5 py-1.5 align-top" />
  ),
  img: (props: ElementProps<'img'>) => {
    const { src, alt, ...rest } = withoutNode(props)
    return (
      <img
        {...rest}
        src={resolveKnowledgeSrc(src ?? '')}
        alt={alt ?? ''}
        loading="lazy"
        className="border-gray-blue my-3 block h-auto max-w-full border bg-white"
        onError={(event) => {
          // Example URLs in manuals are often placeholders and may 404.
          event.currentTarget.style.display = 'none'
        }}
      />
    )
  },
} satisfies MarkdownComponents

/**
 * Renders a knowledge-base section: breadcrumbs, heading, and markdown body.
 */
export default function KnowledgeSectionContent({ section, className }: KnowledgeSectionContentProps) {
  const content = prepareManualMarkdown(section.content)
  const hasContent = Boolean(content.trim())

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

      <h1 className="text-black text-2xl font-bold">{section.title_line}</h1>

      {hasContent ? (
        <div className="text-black text-sm leading-relaxed">
          <Markdown components={components}>{content}</Markdown>
        </div>
      ) : (
        <p className="text-gray text-sm">В этом разделе нет содержимого.</p>
      )}
    </article>
  )
}
