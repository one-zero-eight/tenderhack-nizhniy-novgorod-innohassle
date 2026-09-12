import { createFileRoute, Link } from '@tanstack/react-router'
import KnowledgeSectionContent from '@/components/knowledge/KnowledgeSectionContent'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useSection } from '@/hooks/useKnowledge'

export const Route = createFileRoute('/knowledge-base/$slug/$sectionId')({
  component: SectionPage,
})

function SectionPage() {
  const { slug, sectionId } = Route.useParams()
  const section = useSection(slug, sectionId)

  if (section.isLoading) {
    return (
      <div className="flex justify-center py-10">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (section.isError || !section.data) {
    return (
      <div className="flex flex-col items-center gap-3 py-10">
        <p className="text-red text-sm">{section.error?.message || 'Раздел не найден'}</p>
        <Link to="/knowledge-base/$slug" params={{ slug }} className="text-main-blue text-sm underline underline-offset-4">
          К содержанию руководства
        </Link>
      </div>
    )
  }

  return <KnowledgeSectionContent section={section.data} />
}
