import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/knowledge-base/$slug/')({
  component: ManualIndex,
})

function ManualIndex() {
  return <p className="text-gray text-sm">Выберите раздел из содержания.</p>
}
