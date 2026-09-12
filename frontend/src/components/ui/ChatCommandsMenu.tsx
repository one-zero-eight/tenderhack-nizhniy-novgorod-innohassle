import { FaBolt } from 'react-icons/fa6'
import { cn } from '@/lib/cn'

/** A slash-command offered by the composer's commands menu. */
export interface ChatCommand {
  /** Text pasted into the composer when the command is picked. */
  value: string
  /** Short label shown in the menu; falls back to `value`. */
  label?: string
  /** Small explanation shown under the command. */
  description?: string
}

interface ChatCommandsMenuProps {
  commands: ChatCommand[]
  /** Called when a command is picked; the caller pastes it into the input. */
  onSelect?: (command: ChatCommand) => void
  disabled?: boolean
  className?: string
}

/**
 * Button that reveals the available slash-commands on hover/focus.
 *
 * Picking a command does not run it: the command text is pasted into the
 * composer and still has to be sent by the user for it to take effect.
 */
export default function ChatCommandsMenu({ commands, onSelect, disabled = false, className }: ChatCommandsMenuProps) {
  if (commands.length === 0) return null

  return (
    <div className={cn('group relative', className)}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-label="Команды"
        className={cn(
          'flex items-center gap-2 border border-main-blue/20 bg-white px-5 py-2 text-base font-semibold text-main-blue',
          'transition-colors hover:border-main-blue/50 active:bg-pale-blue/40',
          'focus:outline-red/40 disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <FaBolt />
        <span>Команды</span>
      </button>

      <div
        role="menu"
        className={cn(
          'invisible absolute right-0 bottom-full z-20 mb-2 w-72 -translate-y-1 border border-gray-blue bg-white p-1 opacity-0 shadow-lg transition-all',
          'group-hover:visible group-hover:translate-y-0 group-hover:opacity-100',
          'group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100',
        )}
      >
        {commands.map((command) => (
          <button
            key={command.value}
            type="button"
            role="menuitem"
            disabled={disabled}
            onClick={() => onSelect?.(command)}
            className="flex w-full cursor-pointer flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-pale-blue/50 focus:bg-pale-blue/50 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="text-main-blue text-sm font-semibold">{command.label ?? command.value}</span>
            {command.description && <span className="text-gray text-xs">{command.description}</span>}
          </button>
        ))}
      </div>
    </div>
  )
}
