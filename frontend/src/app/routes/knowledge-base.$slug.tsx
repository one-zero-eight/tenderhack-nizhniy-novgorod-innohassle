import { createFileRoute, Link, Outlet, useParams } from '@tanstack/react-router'
import KnowledgeSidebar from '@/components/knowledge/KnowledgeSidebar'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useManualStructure } from '@/hooks/useKnowledge'
import { requireAuth } from '@/app/routes/-guards'

export const Route = createFileRoute('/knowledge-base/$slug')({
  beforeLoad: requireAuth,
  component: ManualLayout,
})

/**
 * Layout for a single manual: a sticky table of contents on the left and the
 * active section (or the "select a section" placeholder) on the right.
 */
function ManualLayout() {
  const { slug } = Route.useParams()
  // `sectionId` is only present on the child route; used to highlight the ToC.
  const { sectionId } = useParams({ strict: false })
  const { data: manual, isLoading, isError, error, refetch } = useManualStructure(slug)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <Link to="/knowledge-base" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
        ← Все руководства
      </Link>

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить руководство'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <aside className="border-gray-blue w-full shrink-0 overflow-y-auto border bg-white p-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:w-80">
            <h2 className="text-black mb-3 text-sm font-bold">{manual?.title}</h2>
            <KnowledgeSidebar slug={slug} sections={manual?.sections ?? []} activeSectionId={sectionId} />
          </aside>

          <div className="min-w-0 flex-1 rounded bg-white/80 p-4">
            <Outlet />
          </div>
        </div>
      )}
    </div>
  )
}
