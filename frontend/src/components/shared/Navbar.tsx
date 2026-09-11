import Button from '@/components/ui/Button'
import { Link as RouterLink, useLocation, useNavigate } from '@tanstack/react-router'
import { MdOutlineUploadFile } from 'react-icons/md'
import { HiOutlineClipboardDocumentList } from 'react-icons/hi2'
import { $api } from '@/api'

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
  const navigate = useNavigate()
  const { data: stats } = $api.useQuery('get', '/stats')
  const dataPresent = (stats?.cte_count ?? 0) > 0 && (stats?.history_contract_count ?? 0) > 0

  return <nav className="border-gray-blue flex w-full items-center justify-between gap-4 border-b bg-white px-4 py-3"></nav>
}
