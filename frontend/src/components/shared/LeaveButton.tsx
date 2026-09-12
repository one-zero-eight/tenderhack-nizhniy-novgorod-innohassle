import Button from '@/components/ui/Button'
import { FaUser } from 'react-icons/fa'
import { FaDoorOpen } from 'react-icons/fa6'
import { useAuth } from '@/app/providers/auth-context'
import { useState } from 'react'

export default function LeaveButton() {
  const { user, logout } = useAuth()
  const [hovered, setHovered] = useState(false)

  const label = user?.display_name || user?.login || 'Профиль'

  return (
    <Button
      variant="ghost"
      size="sm"
      className="flex items-center gap-2"
      onClick={logout}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {hovered ? (
        <>
          <FaDoorOpen />
          <span>Выйти</span>
        </>
      ) : (
        <>
          <FaUser />
          <span>{label}</span>
        </>
      )}
    </Button>
  )
}
