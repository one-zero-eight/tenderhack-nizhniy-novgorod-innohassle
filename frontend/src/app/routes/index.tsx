import { createFileRoute } from '@tanstack/react-router'

const IndexPage = () => (
  <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-4 px-4">
    <h1 className="text-4xl font-bold text-pale-black">ИИ Ассистент</h1>
  </div>
)

export const Route = createFileRoute('/')({
  component: IndexPage,
})
