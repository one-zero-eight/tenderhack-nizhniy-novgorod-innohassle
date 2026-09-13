import { createFileRoute, Link } from '@tanstack/react-router'
import { FaBookOpen, FaWandMagicSparkles } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useAuth } from '@/app/providers/auth-context'
import { useManuals } from '@/hooks/useKnowledge'
import { requireAuth } from '@/app/routes/-guards'
import { Role } from '@/api/types'

export const Route = createFileRoute('/knowledge-base/')({
  beforeLoad: requireAuth,
  component: KnowledgeIndexPage,
})

function KnowledgeIndexPage() {
  const { data: manuals, isLoading, isError, error, refetch } = useManuals()
  const { user } = useAuth()
  const isAdmin = user?.role === Role.admin

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <h1 className="text-black text-2xl font-bold">База знаний</h1>

      {/* Hand-rules live alongside the manuals but are admin-only. */}
      {isAdmin && (
        <div className="border-gray-blue flex flex-wrap items-center justify-between gap-4 border p-4">
          <div className="flex items-center gap-3">
            <FaWandMagicSparkles className="text-main-blue size-5 shrink-0" />
            <div className="flex flex-col">
              <span className="text-black text-sm font-medium">Правила заданные администратором</span>
              <span className="text-gray text-xs">
                Инструкции ассистенту для отдельных вопросов. Перебивают общие указания промпта.
              </span>
            </div>
          </div>
          <Link to="/handrules" className="shrink-0">
            <Button variant="outline" className="flex items-center gap-2">
              <FaBookOpen className="size-4" />
              Перейти к правилам
            </Button>
          </Link>
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить базу знаний'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : (manuals ?? []).length === 0 ? (
        <p className="text-gray text-sm">Руководства не найдены.</p>
      ) : (
        <ul className="flex flex-col">
          {(manuals ?? []).map((manual) => (
            <li key={manual.slug} className="border-gray-blue border-b last:border-b-0">
              <Link
                to="/knowledge-base/$slug"
                params={{ slug: manual.slug }}
                className="hover:bg-pale-blue/50 flex flex-col gap-1 px-3 py-4 no-underline transition-colors"
              >
                <span className="text-black text-sm font-medium">{manual.title}</span>
                <span className="text-gray text-xs">{manual.sections} разделов</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
