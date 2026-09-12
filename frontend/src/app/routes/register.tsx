import { createFileRoute, Link, redirect, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { useRegister } from '@/hooks/useAuth'
import { getToken } from '@/lib/auth-storage'
import { Role } from '@/api/types'

export const Route = createFileRoute('/register')({
  beforeLoad: () => {
    if (getToken()) {
      throw redirect({ to: '/support' })
    }
  },
  component: RegisterPage,
})

function RegisterPage() {
  const navigate = useNavigate()
  const register = useRegister()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')

  const trimmedLogin = login.trim()
  const trimmedDisplayName = displayName.trim()
  const canSubmit = trimmedLogin.length > 0 && password.length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || register.isPending) return
    register.mutate(
      {
        login: trimmedLogin,
        password,
        // Self-registration always creates a regular user. The endpoint accepts
        // `role` but exposing it here would allow privilege escalation.
        role: Role.user,
        // Omitted when blank so the backend keeps its default display name.
        ...(trimmedDisplayName ? { display_name: trimmedDisplayName } : {}),
      },
      { onSuccess: () => navigate({ to: '/support' }) },
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-6 px-4">
      <h1 className="text-3xl font-bold text-pale-black">Регистрация</h1>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
        <Input
          label="Логин"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
          placeholder="Придумайте логин..."
          autoComplete="username"
          autoFocus
        />
        <Input
          label="Отображаемое имя"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Как к вам обращаться (необязательно)"
          autoComplete="name"
        />
        <Input
          label="Пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Придумайте пароль..."
          autoComplete="new-password"
        />
        {register.isError && (
          <p className="text-red text-sm">{register.error?.message || 'Не удалось зарегистрироваться'}</p>
        )}
        <Button type="submit" variant="primary" disabled={!canSubmit || register.isPending} className="w-full">
          {register.isPending ? 'Регистрация...' : 'Зарегистрироваться'}
        </Button>
      </form>
      <p className="text-gray text-sm">
        Уже есть аккаунт?{' '}
        <Link to="/auth" className="text-main-blue underline underline-offset-4">
          Войти
        </Link>
      </p>
    </div>
  )
}
