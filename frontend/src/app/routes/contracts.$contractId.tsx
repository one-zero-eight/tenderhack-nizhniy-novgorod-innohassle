import { createFileRoute, Link, useRouter } from '@tanstack/react-router'
import { FaArrowLeft } from 'react-icons/fa6'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireAuth } from '@/app/routes/-guards'
import { useContract } from '@/hooks/useProfile'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { SchemaPartyOut } from '@/api/types'

/**
 * Single contract view.
 *
 * Deliberately not linked from the navbar: it is reachable only by clicking a
 * contract referenced in a chat message or listed on the profile page.
 */
export const Route = createFileRoute('/contracts/$contractId')({
  beforeLoad: requireAuth,
  component: ContractPage,
})

/** Formats a number as Russian roubles. */
function formatMoney(value: number, currency = 'RUB'): string {
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value)
}

/** Formats a byte count as a short human-readable size. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/** A labeled value. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-gray text-[0.6875rem] font-semibold tracking-wide uppercase">{label}</dt>
      <dd className="text-black text-sm break-words">{children}</dd>
    </div>
  )
}

/** One side of the contract. */
function Party({ party }: { party: SchemaPartyOut }) {
  return (
    <div className="border-gray-blue flex flex-col gap-2 border p-4">
      <span className="bg-pale-blue text-main-blue w-fit px-2 py-0.5 text-xs font-medium">{party.role_label}</span>
      <span className="text-black text-sm font-bold break-words">{party.company_name}</span>
      <dl className="grid gap-2 text-xs">
        <Field label="ИНН">{party.inn}</Field>
        <Field label="КПП">{party.kpp}</Field>
        <Field label="Представитель">{party.representative}</Field>
      </dl>
    </div>
  )
}

function ContractPage() {
  const { contractId } = Route.useParams()
  const router = useRouter()
  const { data: contract, isLoading, isError, error } = useContract(contractId)

  // Return to wherever the contract was opened from (chat or profile).
  const goBack = () => router.history.back()

  if (isLoading) {
    return (
      <div className="flex flex-1 justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (isError || !contract) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4">
        <p className="text-red text-sm">{error?.message || 'Контракт не найден'}</p>
        <Link to="/profile" className="text-main-blue text-sm underline underline-offset-4">
          Вернуться в профиль
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <button
        type="button"
        onClick={goBack}
        className="text-gray hover:text-main-blue flex w-fit items-center gap-1.5 text-xs underline underline-offset-4 transition-colors"
      >
        <FaArrowLeft className="size-3" />
        Назад
      </button>

      <header className="border-gray-blue border">
        <div className="bg-pale-blue/40 flex flex-col gap-2 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h1 className="text-black min-w-0 text-2xl font-bold break-words">{contract.title}</h1>
            <span className="bg-pale-blue text-main-blue px-2 py-0.5 text-xs font-medium whitespace-nowrap">
              {contract.status}
            </span>
          </div>
          <span className="text-gray font-mono text-xs">{contract.id}</span>
        </div>

        <dl className="grid gap-x-6 gap-y-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Предмет">{contract.subject}</Field>
          <Field label="Цена">{formatMoney(contract.price, contract.currency)}</Field>
          <Field label="Срок исполнения">{contract.execution_period}</Field>
          <Field label="Этап">{contract.execution_stage}</Field>
          <Field label="Ответственный">{contract.responsible_person}</Field>
        </dl>
      </header>

      <section className="flex flex-col gap-3">
        <div className="border-gray-blue border-b pb-1.5">
          <h2 className="text-black text-base font-bold">Стороны</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Party party={contract.parties.customer} />
          <Party party={contract.parties.supplier} />
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div className="border-gray-blue flex items-baseline justify-between gap-3 border-b pb-1.5">
          <h2 className="text-black text-base font-bold">Документы</h2>
          <span className="text-gray text-xs">{contract.documents?.length ?? 0}</span>
        </div>
        {(contract.documents ?? []).length === 0 ? (
          <p className="text-gray text-sm">Документов нет.</p>
        ) : (
          <ul className="border-gray-blue flex flex-col border">
            {(contract.documents ?? []).map((doc) => (
              <li
                key={doc.id}
                className={cn(
                  'border-gray-blue flex items-center justify-between gap-3 border-b px-3 py-2 text-sm last:border-b-0',
                  'hover:bg-pale-blue/40 transition-colors',
                )}
              >
                <span className="text-black truncate" title={doc.title}>
                  {doc.title}
                </span>
                <span className="text-gray shrink-0 text-xs">
                  {doc.file_type} · {formatSize(doc.size_bytes)} · {formatDateTime(doc.uploaded_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
