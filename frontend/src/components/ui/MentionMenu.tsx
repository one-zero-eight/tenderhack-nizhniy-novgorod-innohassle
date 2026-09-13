import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { contractLabel, contractToken, chatToken } from '@/lib/contracts'
import type { SchemaContractOut } from '@/api/types'
import type { ChatView } from '@/lib/chat-view'

/** Which group the mention popup is showing. */
type MentionTab = 'contracts' | 'chats'

interface MentionOption {
  id: string
  title: string
  /** Secondary line, e.g. the contract id or the chat status. */
  meta: string
  /** Text inserted into the composer when this option is accepted. */
  token: string
}

interface ChatMentionMenuProps {
  contracts: SchemaContractOut[]
  chats: ChatView[]
  /** Text typed after `@`, used to filter both groups. */
  query: string
  activeIndex: number
  onSelectContract: (contract: SchemaContractOut) => void
  onSelectChat: (chat: ChatView) => void
  onHover: (index: number) => void
  /** Publishes the visible options so the composer can drive keyboard navigation. */
  onOptionsChange?: (options: { token: string }[]) => void
  className?: string
}

/** Case-insensitive match against a title or its secondary value. */
function matches(option: MentionOption, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return option.title.toLowerCase().includes(q) || option.meta.toLowerCase().includes(q)
}

function toContractOption(contract: SchemaContractOut): MentionOption {
  return { id: contract.id, title: contractLabel(contract), meta: contract.id, token: contractToken(contract.id) }
}

function toChatOption(chat: ChatView): MentionOption {
  return { id: chat.id, title: chat.title, meta: chat.status, token: chatToken(chat.title) }
}

/**
 * Popup listing the user's contracts and chats after they type `@`.
 *
 * The two groups are separate tabs so the list stays short. Keyboard handling
 * (arrows, Tab/Enter) lives in the composer; this component owns the tab state
 * and reports hovers.
 */
export default function MentionMenu({
  contracts,
  chats,
  query,
  activeIndex,
  onSelectContract,
  onSelectChat,
  onHover,
  onOptionsChange,
  className,
}: ChatMentionMenuProps) {
  const [tab, setTab] = useState<MentionTab>('contracts')

  const contractOptions = useMemo(
    () => contracts.map(toContractOption).filter((option) => matches(option, query)),
    [contracts, query],
  )
  const chatOptions = useMemo(() => chats.map(toChatOption).filter((option) => matches(option, query)), [chats, query])

  const options = tab === 'contracts' ? contractOptions : chatOptions

  // Let the composer navigate the currently visible options.
  useEffect(() => {
    onOptionsChange?.(options)
  }, [options, onOptionsChange])

  if (contractOptions.length === 0 && chatOptions.length === 0) return null

  const tabs: { value: MentionTab; label: string; count: number }[] = [
    { value: 'contracts', label: 'Контракты', count: contractOptions.length },
    { value: 'chats', label: 'Чаты', count: chatOptions.length },
  ]

  return (
    <div
      role="listbox"
      aria-label="Вложения"
      className={cn(
        'border-gray-blue absolute bottom-full left-0 z-30 mb-1 max-h-72 w-full overflow-hidden border bg-white shadow-lg',
        className,
      )}
    >
      {/* Group switcher, so contracts and chats do not mix in one list. */}
      <div className="border-gray-blue flex border-b" role="tablist">
        {tabs.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={tab === item.value}
            // Keep focus in the textarea so the caret stays valid.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => setTab(item.value)}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 text-[0.6875rem] font-semibold tracking-wide uppercase transition-colors',
              tab === item.value ? 'text-black border-red border-b-2' : 'text-gray hover:text-black',
            )}
          >
            {item.label}
            <span className="text-gray text-[0.6875rem] font-medium">{item.count}</span>
          </button>
        ))}
      </div>

      <div className="max-h-60 overflow-auto">
        {options.length === 0 ? (
          <p className="text-gray px-3 py-3 text-sm">Ничего не найдено.</p>
        ) : (
          options.map((option, index) => (
            <button
              key={option.id}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              onMouseEnter={() => onHover(index)}
              // `onMouseDown` fires before the textarea loses focus, so the caret
              // position is still valid when the composer inserts the token.
              onMouseDown={(event) => {
                event.preventDefault()
                if (tab === 'contracts') onSelectContract(contracts.find((c) => c.id === option.id) as SchemaContractOut)
                else onSelectChat(chats.find((c) => c.id === option.id) as ChatView)
              }}
              className={cn(
                'flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors',
                index === activeIndex ? 'bg-pale-blue/70' : undefined,
              )}
            >
              <span className="text-black truncate text-sm font-medium">{option.title}</span>
              <span className="text-gray truncate font-mono text-xs">{option.meta}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
