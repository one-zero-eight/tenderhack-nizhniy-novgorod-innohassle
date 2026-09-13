import { Link, createFileRoute } from '@tanstack/react-router'
import { useMemo } from 'react'
import { Markdown, type MarkdownComponentProps, type MarkdownComponents } from '@tanstack/markdown/react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Disclosure from '@/components/ui/Disclosure'
import ChatRow, { ChatRowHeader } from '@/components/ui/ChatRow'
import { useAllAdminChats } from '@/hooks/useAdminChats'
import { useTopicSummary } from '@/hooks/useTopicSummary'
import { chatsForTopic, summarizeSubtopics } from '@/lib/issues'
import { cn } from '@/lib/cn'
export const Route = createFileRoute('/issues/$topic/')({
  component: TopicPage,
})

/** Russian plural form for «обращение». */
function pluralChats(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'обращение'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'обращения'
  return 'обращений'
}

function TopicPage() {
  const { topic } = Route.useParams()
  const { data: chats, isLoading, isError, error, refetch } = useAllAdminChats()

  const allChats = useMemo(() => chats ?? [], [chats])
  const subtopics = useMemo(() => summarizeSubtopics(allChats, topic), [allChats, topic])
  const topicTotal = useMemo(() => chatsForTopic(allChats, topic, null).length, [allChats, topic])

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <div className="flex flex-col gap-1">
        <Link to="/issues" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
          ← Типичные проблемы
        </Link>
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-black text-2xl font-bold">{topic}</h1>
          {!isLoading && <span className="text-gray text-sm">Обращений: {topicTotal}</span>}
        </div>
      </div>

      {/* AI summary of the topic's recurring problems. */}
      <TopicSummaryCard topic={topic} />

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить данные'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : subtopics.length === 0 ? (
        <p className="text-gray text-sm">Обращений по этой теме нет.</p>
      ) : (
        // Each subtopic expands to reveal its chats.
        <div className="flex flex-col">
          {subtopics.map((item) => {
            const subtopicChats = chatsForTopic(allChats, topic, item.subtopic)
            return (
              <Disclosure
                key={item.subtopic}
                title={item.subtopic}
                meta={<span className="text-gray shrink-0 text-xs">{item.chatCount} {pluralChats(item.chatCount)}</span>}
              >
                <div className="border-gray-blue border-t">
                  <ChatRowHeader />
                  {subtopicChats.map((chat) => (
                    <ChatRow key={chat.id} chat={chat} to="/issues/$topic/$chatId" params={{ topic }} />
                  ))}
                </div>
              </Disclosure>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * AI-generated summary of the recurring problems in this topic.
 *
 * Placeholder for now: the text is stubbed and will be fetched from the backend
 * once a summary endpoint exists.
 */
/** Props passed to custom components; the parser adds a `node` field we drop. */
type ElementProps<Tag extends keyof React.JSX.IntrinsicElements> = MarkdownComponentProps<Tag> & { node?: unknown }

/** Removes the non-DOM `node` prop before spreading onto an element. */
function withoutNode<T extends { node?: unknown }>({ node, ...rest }: T): Omit<T, 'node'> {
  void node
  return rest
}

/** Compact Markdown styling for the AI summary. */
const components = {
  p: (props: ElementProps<'p'>) => <p {...withoutNode(props)} className="not-first:mt-2" />,
  ul: (props: ElementProps<'ul'>) => <ul {...withoutNode(props)} className="my-2 list-disc space-y-1 pl-5" />,
  ol: (props: ElementProps<'ol'>) => <ol {...withoutNode(props)} className="my-2 list-decimal space-y-1 pl-5" />,
  strong: (props: ElementProps<'strong'>) => <strong {...withoutNode(props)} className="font-semibold" />,
  a: (props: ElementProps<'a'>) => (
    <a {...withoutNode(props)} target="_blank" rel="noopener noreferrer" className="text-main-blue underline underline-offset-2" />
  ),
  code: (props: ElementProps<'code'>) => (
    <code {...withoutNode(props)} className={cn('bg-black/10 rounded px-1 py-0.5 font-mono text-[0.85em]', props.className)} />
  ),
} satisfies MarkdownComponents

function TopicSummaryCard({ topic }: { topic: string }) {
  const { data, isLoading, isError, error, refetch } = useTopicSummary(topic)

  const status = data?.status
  const hasSummary = !!data?.summary

  return (
    <section className="border-gray-blue bg-pale-blue/30 flex flex-col gap-2 border p-4">
      <h2 className="text-main-blue text-xs font-semibold tracking-wide uppercase">Сводка по проблемам</h2>

      {isLoading ? (
        <div className="flex items-center gap-2 py-2">
          <LoadingSpinner size="sm" />
          <span className="text-gray text-sm">Загружаем сводку…</span>
        </div>
      ) : isError ? (
        <div className="flex flex-col items-start gap-2 py-1">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить сводку'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : hasSummary ? (
        // The summary is Markdown (paragraphs, bullet lists).
        <div className="text-black text-sm leading-relaxed">
          <Markdown components={components}>{data?.summary ?? ''}</Markdown>
        </div>
      ) : (
        <p className="text-gray text-sm">
          {status === 'pending' || status === 'outdated'
            ? 'Сводка формируется, это может занять некоторое время.'
            : 'Недостаточно обратной связи по теме для анализа.'}
        </p>
      )}

      {hasSummary && <span className="text-gray text-xs">Сводка сформирована ИИ и может быть неточной.</span>}
    </section>
  )
}
