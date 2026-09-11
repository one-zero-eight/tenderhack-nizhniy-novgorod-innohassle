import Button from '@/components/ui/Button'
import { Link as RouterLink, useLocation, useNavigate } from '@tanstack/react-router'
import { HiOutlineClipboardDocumentList } from 'react-icons/hi2'
import { clearUsername } from '@/lib/storage'
import LeaveButton from './LeaveButton';

function NavLink({ to, children, icon: Icon }: { to: string; children: React.ReactNode; icon?: React.ComponentType<{ className?: string }> }) {
  const { pathname } = useLocation()
  const isActive = to === '/' ? pathname === '/' : pathname.startsWith(to)
  return (
    <RouterLink
      to={to}
      className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium no-underline transition-colors ${isActive ? 'bg-main-blue/10 text-main-blue' : 'text-pale-black hover:bg-pale-blue/50 hover:text-main-blue'}`}
    >
      {Icon && <Icon className="size-4" />}
      {children}
    </RouterLink>
  )
}

export default function Navbar() {

  return (
    <nav className="border-gray-blue flex w-full items-center justify-between gap-4 border-b bg-white px-4 py-3">
      <div className="flex items-center gap-1">
        <RouterLink to="/" className="text-main-blue hover:text-main-blue/80 mr-4 text-lg font-bold no-underline">
          Портал Поставщиков
        </RouterLink>
        <NavLink to="/support" icon={HiOutlineClipboardDocumentList}>
          Поддержка
        </NavLink>
      </div>
      <LeaveButton />
    </nav>
  )
}
