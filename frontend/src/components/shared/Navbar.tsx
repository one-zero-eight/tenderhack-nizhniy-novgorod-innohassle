import { Link as RouterLink, useLocation } from '@tanstack/react-router'
import { FaBook, FaHeadset, FaClockRotateLeft, FaTriangleExclamation } from 'react-icons/fa6'
import { useAuth } from '@/app/providers/auth-context'
import { Role } from '@/api/types'
import { navButtonClasses } from './nav-button'
import LeaveButton from './LeaveButton'

function NavLink({ to, children, icon: Icon }: { to: string; children: React.ReactNode; icon?: React.ComponentType<{ className?: string }> }) {
  const { pathname } = useLocation()
  const isActive = to === '/' ? pathname === '/' : pathname.startsWith(to)
  return (
    <RouterLink to={to} className={navButtonClasses(isActive)}>
      {Icon && <Icon className="size-4" />}
      {children}
    </RouterLink>
  )
}

export default function Navbar() {
  const { user } = useAuth()
  const isAdmin = user?.role === Role.admin

  return (
    <nav className="border-gray-blue flex h-16 w-full items-stretch justify-between border-b bg-white px-4">
      <div className="flex items-stretch">
        <RouterLink to="/" className="mr-4 flex items-center no-underline" aria-label="Портал Поставщиков">
          <img
            src="https://zakupki.mos.ru/cms/Media/holidaysthemes/pplogo/pp_logo.svg"
            alt="Портал Поставщиков"
            className="h-8 w-auto"
          />
        </RouterLink>
        {isAdmin ? (
          <>
            <NavLink to="/knowledge" icon={FaBook}>
              База знаний
            </NavLink>
            <NavLink to="/history" icon={FaClockRotateLeft}>
              История обращений
            </NavLink>
            <NavLink to="/issues" icon={FaTriangleExclamation}>
              Типичные проблемы
            </NavLink>
          </>
        ) : (
          <>
            <NavLink to="/support" icon={FaHeadset}>
              Поддержка
            </NavLink>
            <NavLink to="/knowledge" icon={FaBook}>
              База знаний
            </NavLink>
          </>
        )}
      </div>
      <LeaveButton />
    </nav>
  )
}
