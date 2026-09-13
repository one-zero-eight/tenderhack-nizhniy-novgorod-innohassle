import { Link, createFileRoute } from '@tanstack/react-router'
import { useMemo } from 'react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Disclosure from '@/components/ui/Disclosure'
import ChatRow, { ChatRowHeader } from '@/components/ui/ChatRow'
import { requireRole } from '@/app/routes/-guards'
import { useAllAdminChats } from '@/hooks/useAdminChats'
import { chatsForTopic, summarizeSubtopics, NO_SUBTOPIC } from '@/lib/issues'
import { Role } from '@/api/types'

export const Route = createFileRoute('/issues/$topic')({
  beforeLoad: () => requireRole([Role.admin]),
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
      <TopicSummaryCard topic={topic} chatCount={topicTotal} />

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
                    <ChatRow key={chat.id} chat={chat} to="/history/$chatId" />
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
function TopicSummaryCard({ topic, chatCount }: { topic: string; chatCount: number }) {
  // TODO: replace with a real request, e.g. `GET /admin/topics/{topic}/summary`.
  const summary =
    topic === NO_SUBTOPIC || chatCount === 0
      ? 'Недостаточно данных для анализа.'
      : `Пользователи чаще всего обращаются по теме «${topic}». ИИ-сводка появится после подключения сервиса: она опишет повторяющиеся проблемы, частые причины обращений и рекомендуемые шаги для операторов.`

  return (
    <section className="border-gray-blue bg-pale-blue/30 flex flex-col gap-2 border p-4">
      <h2 className="text-main-blue text-xs font-semibold tracking-wide uppercase">Сводка по проблемам</h2>
      <p className="text-black text-sm leading-relaxed whitespace-pre-wrap">{summary}</p>
      <span className="text-gray text-xs">Сводка сформирована ИИ и может быть неточной.</span>
    </section>
  )
}
