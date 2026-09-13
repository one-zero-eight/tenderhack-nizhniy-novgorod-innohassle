import { useState, type FormEvent } from 'react'
import { FaXmark } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/cn'

interface HandRuleModalProps {
  /** Prefilled question. Empty when creating from the rules page. */
  defaultUserMessage: string
  /** Prefilled instruction. Empty when creating from the rules page. */
  defaultInstructions: string
  onSubmit: (userMessage: string, instructions: string) => void
  onClose: () => void
  /**
   * `edit` switches the labels to update wording; the fields and validation are
   * identical to `create`.
   */
  mode?: 'create' | 'edit'
  submitting?: boolean
  error?: string | null
}

/**
 * Modal for creating or editing a hand-rule: the user's question and the
 * instruction the assistant should follow, both editable before saving.
 */
export default function HandRuleModal({
  defaultUserMessage,
  defaultInstructions,
  onSubmit,
  onClose,
  mode = 'create',
  submitting = false,
  error = null,
}: HandRuleModalProps) {
  const [userMessage, setUserMessage] = useState(defaultUserMessage)
  const [instructions, setInstructions] = useState(defaultInstructions)

  const isEdit = mode === 'edit'
  const canSubmit = userMessage.trim().length > 0 && instructions.trim().length > 0

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit || submitting) return
    onSubmit(userMessage.trim(), instructions.trim())
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={isEdit ? 'Изменение правила администратора' : 'Новое правило администратора'}
    >
      <form
        onSubmit={handleSubmit}
        className={cn(
          'border-pale-blue focus-within:border-main-blue/50 flex w-full max-w-2xl flex-col gap-4 border-2 bg-white p-4 shadow-lg transition-colors',
          submitting ? 'cursor-not-allowed opacity-70' : undefined,
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-black text-base font-bold">{isEdit ? 'Изменение правила' : 'Новое правило администратора'}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            aria-label="Закрыть"
            className="text-gray hover:text-red shrink-0 rounded-full p-1 transition-colors focus:outline-red/40"
          >
            <FaXmark className="size-5" />
          </button>
        </div>

        <p className="text-gray text-sm">
          Правило перебивает общие указания ассистента: похожий по смыслу вопрос получит заданную инструкцию.
        </p>

        <div className="flex flex-col gap-2">
          <label htmlFor="handrule-question" className="text-black text-sm font-bold">
            Вопрос пользователя
          </label>
          <textarea
            id="handrule-question"
            value={userMessage}
            onChange={(e) => setUserMessage(e.target.value)}
            rows={3}
            autoFocus
            placeholder="Введите вопрос пользователя"
            className={cn(
              'border-pale-blue focus:border-main-blue/50 block w-full resize-y border-2 bg-white px-3 py-2 text-sm text-black',
              'placeholder:text-gray outline-none transition-colors',
            )}
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="handrule-answer" className="text-black text-sm font-bold">
            Что отвечать
          </label>
          <textarea
            id="handrule-answer"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={6}
            placeholder="Введите ответ ассистента"
            className={cn(
              'border-pale-blue focus:border-main-blue/50 block w-full resize-y border-2 bg-white px-3 py-2 text-sm text-black',
              'placeholder:text-gray outline-none transition-colors',
            )}
          />
        </div>

        {error && <p className="text-red text-sm">{error}</p>}

        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            Отмена
          </Button>
          <Button type="submit" variant="primary" disabled={!canSubmit || submitting}>
            {submitting ? 'Сохранение...' : isEdit ? 'Сохранить изменения' : 'Создать правило'}
          </Button>
        </div>
      </form>
    </div>
  )
}
