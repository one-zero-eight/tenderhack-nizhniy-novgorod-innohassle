import { createFileRoute } from '@tanstack/react-router'
import { requireAuth } from '@/app/routes/-guards'

export const Route = createFileRoute('/knowledge/')({
  beforeLoad: requireAuth,
  component: KnowledgePage,
})

function KnowledgePage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <h1 className="text-2xl font-bold text-pale-black">База знаний</h1>
      <p className="text-gray text-sm">Раздел наполняется.</p>
    </div>
  )
}
