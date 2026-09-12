import Navbar from '@/components/shared/Navbar'
import Button from '@/components/ui/Button'
import { useAuth } from '@/app/providers/auth-context'
import { Link as RouterLink, Outlet, createRootRoute, useLocation } from '@tanstack/react-router'

const MANUL_BACKGROUND_URL = 'https://zooart.com.pl/blog/wp-content/uploads/2023/01/MANUL-STEPOWY-OLX-1000x667-1.jpg'

const RootLayout = () => {
  const { pathname } = useLocation()
  const { user } = useAuth()
  const isAuthPage = pathname === '/auth' || pathname === '/register'

  // When the signed-in user is «manul», a faint manul image is shown behind
  // every page.
  const isManul = user?.login?.toLowerCase() === 'manul'

  return (
    <div className="bg-pale-blue/30 relative flex h-full min-h-screen flex-col">
      {isManul && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-0 bg-cover bg-center bg-no-repeat opacity-10"
          style={{ backgroundImage: `url(${MANUL_BACKGROUND_URL})` }}
        />
      )}
      <div className="relative z-10 flex flex-1 flex-col">
        {!isAuthPage && <Navbar />}
        <Outlet />
      </div>
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
