import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { useLogin } from '@/hooks/useAuth'
import { getToken } from '@/lib/auth-storage'

export const Route = createFileRoute('/auth')({
  beforeLoad: () => {
    if (getToken()) {
      throw redirect({ to: '/support' })
    }
  },
  component: AuthPage,
})

function AuthPage() {
  const navigate = useNavigate()
  const login = useLogin()
  const [loginValue, setLoginValue] = useState('')
  const [password, setPassword] = useState('')

  const canSubmit = loginValue.trim().length > 0 && password.length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || login.isPending) return
    login.mutate(
      { login: loginValue.trim(), password },
      { onSuccess: () => navigate({ to: '/support' }) },
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-6 px-4">
      <h1 className="text-3xl font-bold text-pale-black">Вход</h1>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
        <Input
          label="Логин"
          value={loginValue}
          onChange={(e) => setLoginValue(e.target.value)}
          placeholder="Введите логин..."
          autoComplete="username"
          autoFocus
        />
        <Input
          label="Пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Введите пароль..."
          autoComplete="current-password"
        />
        {login.isError && <p className="text-red text-sm">{login.error?.message || 'Неверный логин или пароль'}</p>}
        <Button type="submit" variant="primary" disabled={!canSubmit || login.isPending} className="w-full">
          {login.isPending ? 'Вход...' : 'Войти'}
        </Button>
      </form>
    </div>
  )
}
