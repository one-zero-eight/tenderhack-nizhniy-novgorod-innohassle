import { createFileRoute } from '@tanstack/react-router'
import { Link } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { FaMagnifyingGlass, FaPencil, FaPlus, FaTrash } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import HandRuleModal from '@/components/ui/HandRuleModal'
import Input from '@/components/ui/Input'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireRole } from '@/app/routes/-guards'
import { useCreateHandRule, useDeleteHandRule, useHandRules, useUpdateHandRule } from '@/hooks/useHandrules'
import { fuzzyMatchHandRules } from '@/lib/handrules-api'
import { Role } from '@/api/types'
import type { HandRule } from '@/lib/handrules-api'

export const Route = createFileRoute('/handrules/')({
  beforeLoad: () => requireRole([Role.admin]),
  component: HandRulesPage,
})

/**
 * One hand-rule: question on top, agent instruction underneath, with edit and
 * delete actions.
 */
function HandRuleRow({
  rule,
  onEdit,
  onDelete,
  disabled,
}: {
  rule: HandRule
  onEdit: (rule: HandRule) => void
  onDelete: (rule: HandRule) => void
  disabled: boolean
}) {
  return (
    <li className="border-gray-blue flex items-start gap-4 border-b px-4 py-4 last:border-b-0">
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-gray text-xs font-semibold uppercase">Вопрос</span>
          <p className="text-black text-sm break-words whitespace-pre-wrap">{rule.user_message}</p>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-gray text-xs font-semibold uppercase">Ответ агента</span>
          <p className="text-pale-black text-sm break-words whitespace-pre-wrap">{rule.instructions}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={() => onEdit(rule)}
          disabled={disabled}
          aria-label="Изменить правило"
          title="Изменить правило"
          className="text-gray hover:text-main-blue p-1 transition-colors disabled:opacity-50"
        >
          <FaPencil className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => onDelete(rule)}
          disabled={disabled}
          aria-label="Удалить правило"
          title="Удалить правило"
          className="text-gray hover:text-red p-1 transition-colors disabled:opacity-50"
        >
          <FaTrash className="size-4" />
        </button>
      </div>
    </li>
  )
}

function HandRulesPage() {
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<HandRule | null>(null)
  const [pendingDelete, setPendingDelete] = useState<HandRule | null>(null)
  const list = useHandRules()
  const createRule = useCreateHandRule()
  const updateRule = useUpdateHandRule()
  const deleteRule = useDeleteHandRule()

  const searching = query.trim().length > 0
  // Search filters the already-fetched rules locally, so it works even when the
  // ML search service is unavailable and never fires per-keystroke requests.
  const rules = useMemo(() => fuzzyMatchHandRules(list.data ?? [], query), [list.data, query])

  const closeCreateModal = () => {
    setCreating(false)
    createRule.reset()
  }

  const closeEditModal = () => {
    setEditing(null)
    updateRule.reset()
  }

  const closeDeleteDialog = () => {
    setPendingDelete(null)
    deleteRule.reset()
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <Link to="/knowledge-base" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
        ← База знаний
      </Link>

      <div className="flex items-center justify-between gap-4">
        <h1 className="text-black text-2xl font-bold">Правила заданные администратором</h1>
        {!list.isLoading && <span className="text-gray text-sm">Правил: {rules.length}</span>}
      </div>

      <p className="text-gray text-sm">
        Правила перебивают общие указания ассистента: подходящий по смыслу вопрос получает заданную инструкцию вместо
        обычного ответа.
      </p>

      {/* Search over the fetched rules, plus the create action. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-md">
          <FaMagnifyingGlass className="text-gray absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по тексту..." className="pl-9" />
        </div>
        {searching && (
          <button
            type="button"
            onClick={() => setQuery('')}
            className="text-main-blue shrink-0 text-sm underline underline-offset-4"
          >
            Сбросить
          </button>
        )}
        <Button variant="primary" onClick={() => setCreating(true)} className="ml-auto flex items-center gap-2">
          <FaPlus className="size-4" />
          Добавить правило
        </Button>
      </div>

      {updateRule.isError && !editing && (
        <p className="text-red text-sm">{updateRule.error?.message || 'Не удалось изменить правило'}</p>
      )}

      {list.isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : list.isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{list.error?.message || 'Не удалось загрузить правила'}</p>
          <button type="button" onClick={() => list.refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : rules.length === 0 ? (
        <p className="text-gray text-sm">{searching ? 'Ничего не найдено.' : 'Правил пока нет.'}</p>
      ) : (
        <ul className="border-gray-blue border">
          {rules.map((rule) => (
            <HandRuleRow
              key={rule.id}
              rule={rule}
              disabled={deleteRule.isPending || updateRule.isPending}
              onEdit={(target) => setEditing(target)}
              onDelete={(target) => setPendingDelete(target)}
            />
          ))}
        </ul>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Удалить правило?"
          destructive
          confirmLabel="Удалить"
          pending={deleteRule.isPending}
          error={deleteRule.isError ? (deleteRule.error?.message ?? 'Не удалось удалить правило') : null}
          message={
            <>
              Правило по вопросу{' '}
              <span className="text-black font-medium">«{pendingDelete.user_message}»</span> будет удалено без
              возможности восстановления.
            </>
          }
          onClose={closeDeleteDialog}
          onConfirm={() => deleteRule.mutate(pendingDelete.id, { onSuccess: closeDeleteDialog })}
        />
      )}

      {creating && (
        <HandRuleModal
          defaultUserMessage=""
          defaultInstructions=""
          submitting={createRule.isPending}
          error={createRule.isError ? (createRule.error?.message ?? 'Не удалось создать правило') : null}
          onClose={closeCreateModal}
          onSubmit={(userMessage, instructions) =>
            createRule.mutate({ user_message: userMessage, instructions }, { onSuccess: closeCreateModal })
          }
        />
      )}

      {editing && (
        <HandRuleModal
          mode="edit"
          defaultUserMessage={editing.user_message}
          defaultInstructions={editing.instructions}
          submitting={updateRule.isPending}
          error={updateRule.isError ? (updateRule.error?.message ?? 'Не удалось изменить правило') : null}
          onClose={closeEditModal}
          onSubmit={(userMessage, instructions) =>
            updateRule.mutate(
              { ruleId: editing.id, patch: { user_message: userMessage, instructions } },
              { onSuccess: closeEditModal },
            )
          }
        />
      )}
    </div>
  )
}
