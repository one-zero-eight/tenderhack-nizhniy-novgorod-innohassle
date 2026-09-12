import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { FaUser } from 'react-icons/fa'
import { FaDoorOpen } from 'react-icons/fa6'
import { useAuth } from '@/app/providers/auth-context'
import { roleLabel } from '@/lib/roles'
import { navButtonClasses } from './nav-button'

export default function LeaveButton() {
  const { user, logout } = useAuth()

  const label = user?.display_name || user?.login || 'Профиль'
  return (
    <Menu as="div" className="relative flex">
      <MenuButton className={navButtonClasses(false, 'data-open:bg-pale-blue/50 min-w-46')} title={label}>
        <FaUser className="shrink-0" />
        <span className="truncate">{label}</span>
      </MenuButton>

      {/*
        Anchored below the button and sized to exactly match its width
        (`--button-width` is provided by Headless UI). The panel reads as an
        extension of the profile button rather than a floating popover.
      */}
      <MenuItems
        anchor={{ to: 'bottom', gap: 0 }}
        className="border-gray-blue z-50 w-[var(--button-width)] border border-t-0 bg-white shadow-lg focus:outline-none"
      >
        {user && (
          <div className="flex flex-col items-center justify-center gap-1 border-gray-blue text-gray border-b px-5 py-2 text-xs">
            <span>{user.login}</span><span className="text-main-blue font-medium">{roleLabel(user.role)}</span>
          </div>
        )}
        <MenuItem>
          <button
            type="button"
            onClick={logout}
            className="text-black data-focus:bg-pale-blue/50 data-focus:text-main-blue flex w-full items-center justify-center gap-2 px-5 py-3 text-sm font-medium transition-colors"
          >
            <FaDoorOpen className="shrink-0" />
            <span>Выйти</span>
          </button>
        </MenuItem>
      </MenuItems>
    </Menu>
  )
}
