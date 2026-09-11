import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { getUsername, setUsername } from '@/lib/storage'

export const Route = createFileRoute('/auth')({
  beforeLoad: () => {
    if (getUsername()) {
      throw redirect({ to: '/support' })
    }
  },
  component: AuthPage,
})

function AuthPage() {
  const navigate = useNavigate()
  const [value, setValue] = useState('')

  const trimmed = value.trim()
  const canSubmit = trimmed.length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setUsername(trimmed)
    navigate({ to: '/support' })
  }

  return (
    <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-6 px-4">
      <h1 className="text-3xl font-bold text-pale-black">Вход</h1>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
        <Input
          label="Имя пользователя"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Введите имя пользователя..."
          autoFocus
        />
        <Button type="submit" variant="primary" disabled={!canSubmit} className="w-full">
          Войти
        </Button>
      </form>
    </div>
  )
}
