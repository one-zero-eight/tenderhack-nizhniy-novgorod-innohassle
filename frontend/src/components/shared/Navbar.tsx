import { Link as RouterLink, useLocation } from '@tanstack/react-router'
import { FaHeadset } from 'react-icons/fa6'
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
  return (
    <nav className="border-gray-blue flex h-16 w-full items-stretch justify-between border-b bg-white px-4">
      <div className="flex items-stretch">
        <RouterLink to="/" className="text-main-blue hover:text-main-blue/80 mr-4 flex items-center text-lg font-bold no-underline">
          Портал Поставщиков
        </RouterLink>
        <NavLink to="/support" icon={FaHeadset}>
          Поддержка
        </NavLink>
      </div>
      <LeaveButton />
    </nav>
  )
}
