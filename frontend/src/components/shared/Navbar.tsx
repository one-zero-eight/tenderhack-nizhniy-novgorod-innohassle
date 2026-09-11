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

  return (
    <nav className="border-gray-blue flex w-full items-center justify-between gap-4 border-b bg-white px-4 py-3">
      <div className="flex items-center gap-1">
        <RouterLink to="/" className="text-main-blue hover:text-main-blue/80 mr-4 text-lg font-bold no-underline">
          Обоснование цены
        </RouterLink>
        <NavLink to="/" icon={HiOutlineClipboardDocumentList}>
          Контракты
        </NavLink>
      </div>
      <div className="flex items-center gap-5">
        <span className={`flex items-center gap-1.5 text-sm ${dataPresent ? 'text-green-600' : 'text-red-600'}`}>
          <span className={`size-2 shrink-0 rounded-full ${dataPresent ? 'bg-green-600' : 'bg-red-600'}`} />
          {dataPresent ? `${(stats?.cte_count ?? 0).toLocaleString('ru-RU')} СТЕ, ${(stats?.history_contract_count ?? 0).toLocaleString('ru-RU')} контрактов` : 'Нет данных'}
        </span>
        <Button variant="primary" size="sm" className="flex items-center gap-2" onClick={() => navigate({ to: '/upload' })}>
          <MdOutlineUploadFile className="size-5" />
          Загрузка
        </Button>
      </div>
    </nav>
  )
}
