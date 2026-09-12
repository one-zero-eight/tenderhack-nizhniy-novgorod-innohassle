import Navbar from '@/components/shared/Navbar'
import Button from '@/components/ui/Button'
import { Link as RouterLink, Outlet, createRootRoute, useLocation } from '@tanstack/react-router'

const RootLayout = () => {
  const { pathname } = useLocation()
  const isAuthPage = pathname === '/auth' || pathname === '/register'

  return (
    <div className="bg-pale-blue/30 flex h-full min-h-screen flex-col">
      {!isAuthPage && <Navbar />}
      <Outlet />
    </div>
  )
}

function NotFoundComponent() {
  return (
    <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-4 px-4">
      <h1 className="text-4xl font-bold text-pale-black">404</h1>
      <p className="text-pale-black text-center">Страница не найдена</p>
      <RouterLink to="/">
        <Button variant="primary">На главную</Button>
      </RouterLink>
    </div>
  )
}

export const Route = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundComponent,
})
