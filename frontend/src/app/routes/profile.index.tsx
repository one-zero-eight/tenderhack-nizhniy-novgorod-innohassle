import { createFileRoute, Link } from '@tanstack/react-router'
import { useAuth } from '@/app/providers/auth-context'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireAuth } from '@/app/routes/-guards'
import { useProfile } from '@/hooks/useProfile'
import { roleLabel } from '@/lib/roles'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { SchemaDocumentOut } from '@/api/types'

export const Route = createFileRoute('/profile/')({
  beforeLoad: requireAuth,
  component: ProfilePage,
})

/** A label/value row. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-gray-blue flex flex-col gap-0.5 border-b py-3 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-4">
      <dt className="text-main-blue w-56 shrink-0 text-xs font-semibold tracking-wide uppercase">{label}</dt>
      <dd className="text-black text-sm break-words">{children}</dd>
    </div>
  )
}

/** A titled section with bordered content. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-black text-base font-bold">{title}</h2>
      {children}
    </section>
  )
}

/** Formats a byte count as a short human-readable size. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/** Formats a number as Russian roubles. */
function formatMoney(value: number, currency = 'RUB'): string {
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value)
}

/** A compact list of documents, or a placeholder when there are none. */
function DocumentList({ documents }: { documents?: SchemaDocumentOut[] }) {
  const items = documents ?? []
  if (items.length === 0) return <p className="text-gray text-sm">Документов нет.</p>
  return (
    <ul className="border-gray-blue flex flex-col border">
      {items.map((doc) => (
        <li key={doc.id} className="border-gray-blue flex items-center justify-between gap-3 border-b px-3 py-2 text-sm last:border-b-0">
          <span className="text-black truncate" title={doc.title}>
            {doc.title}
          </span>
          <span className="text-gray shrink-0 text-xs">
            {doc.file_type} · {formatSize(doc.size_bytes)} · {formatDateTime(doc.uploaded_at)}
          </span>
        </li>
      ))}
    </ul>
  )
}

function ProfilePage() {
  const { user, isLoading: userLoading } = useAuth()
  const { data: profile, isLoading, isError, error, refetch } = useProfile()

  if (userLoading || isLoading) {
    return (
      <div className="flex flex-1 justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (isError || !profile || !user) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4">
        <p className="text-red text-sm">{error?.message || 'Не удалось загрузить профиль'}</p>
        <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
          Повторить
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-8">
      <h1 className="text-black text-2xl font-bold">Профиль</h1>

      {/* Account ------------------------------------------------------------------ */}
      <Section title="Учётная запись">
        <dl className="border-gray-blue border">
          <div className="px-4">
            <Field label="Отображаемое имя">{profile.display_name || user.display_name || '—'}</Field>
            <Field label="Логин">{user.login}</Field>
            <Field label="Роль">{roleLabel(profile.role)}</Field>
          </div>
        </dl>
      </Section>

      {/* Company ------------------------------------------------------------------ */}
      <Section title="Организация">
        <dl className="border-gray-blue border">
          <div className="px-4">
            <Field label="Название">{profile.company.name}</Field>
            {profile.company.full_name && <Field label="Полное наименование">{profile.company.full_name}</Field>}
            <Field label="ИНН">{profile.company.inn}</Field>
            <Field label="КПП">{profile.company.kpp}</Field>
            <Field label="ОГРН">{profile.company.ogrn}</Field>
            <Field label="Адрес">{profile.company.address}</Field>
            <Field label="Руководитель">{profile.company.ceo}</Field>
            <Field label="Телефон">
              <a href={`tel:${profile.company.phone}`} className="text-main-blue underline underline-offset-2">
                {profile.company.phone}
              </a>
            </Field>
            <Field label="E-mail">
              <a href={`mailto:${profile.company.email}`} className="text-main-blue underline underline-offset-2">
                {profile.company.email}
              </a>
            </Field>
            <Field label="Сайт">
              {profile.company.website ? (
                <a
                  href={profile.company.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-main-blue underline underline-offset-2"
                >
                  {profile.company.website}
                </a>
              ) : (
                '—'
              )}
            </Field>
            <Field label="Роль организации">{profile.company.role_label}</Field>
          </div>
        </dl>
        {profile.company.documents && profile.company.documents.length > 0 && (
          <div className="mt-2 flex flex-col gap-2">
            <h3 className="text-gray text-xs font-semibold uppercase">Документы организации</h3>
            <DocumentList documents={profile.company.documents} />
          </div>
        )}
      </Section>

      {/* Procurements ------------------------------------------------------------- */}
      <Section title={`Закупки (${profile.procurements.length})`}>
        {profile.procurements.length === 0 ? (
          <p className="text-gray text-sm">Закупок нет.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {profile.procurements.map((procurement) => (
              <li key={procurement.id} className={cn('border-gray-blue flex flex-col gap-2 border p-3')}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-black font-medium">{procurement.title}</span>
                  <span className="bg-pale-blue text-main-blue px-2 py-0.5 text-xs font-medium">{procurement.status}</span>
                </div>
                <div className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                  <span className="text-black">Номер: {procurement.number}</span>
                  <span className="text-black">
                    Заказчик: {procurement.customer_name} (ИНН {procurement.customer_inn})
                  </span>
                  <span className="text-black">Начальная цена: {formatMoney(procurement.initial_price, procurement.currency)}</span>
                  <span className="text-black">Предложений: {procurement.offers_count}</span>
                  <span className="text-gray">Опубликовано: {formatDateTime(procurement.published_at)}</span>
                  <span className="text-gray">Приём заявок до: {formatDateTime(procurement.submission_deadline)}</span>
                </div>
                {(procurement.documents ?? []).length > 0 && <DocumentList documents={procurement.documents} />}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Offers ------------------------------------------------------------------- */}
      <Section title={`Предложения (${profile.offers.length})`}>
        {profile.offers.length === 0 ? (
          <p className="text-gray text-sm">Предложений нет.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {profile.offers.map((offer) => (
              <li key={offer.id} className="border-gray-blue flex flex-col gap-2 border p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-black font-medium">{offer.procurement_title}</span>
                  <span className="flex items-center gap-2">
                    {offer.is_winner && <span className="bg-green/10 text-green px-2 py-0.5 text-xs font-semibold">Победитель</span>}
                    <span className="bg-pale-blue text-main-blue px-2 py-0.5 text-xs font-medium">{offer.status}</span>
                  </span>
                </div>
                <div className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                  <span className="text-black">Поставщик: {offer.supplier_name} (ИНН {offer.supplier_inn})</span>
                  <span className="text-black">Цена: {formatMoney(offer.price)}</span>
                  <span className="text-gray">Подано: {formatDateTime(offer.submitted_at)}</span>
                </div>
                {offer.details && <p className="text-black text-sm">{offer.details}</p>}
                {(offer.documents ?? []).length > 0 && <DocumentList documents={offer.documents} />}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Contracts ---------------------------------------------------------------- */}
      <Section title={`Контракты (${profile.contracts.length})`}>
        {profile.contracts.length === 0 ? (
          <p className="text-gray text-sm">Контрактов нет.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {profile.contracts.map((contract) => (
              <li key={contract.id} className="border-gray-blue hover:border-main-blue/40 flex flex-col gap-2 border p-3 transition-colors">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link
                    to="/contracts/$contractId"
                    params={{ contractId: contract.id }}
                    className="text-main-blue min-w-0 font-medium break-words underline underline-offset-2"
                  >
                    {contract.title}
                  </Link>
                  <span className="bg-pale-blue text-main-blue px-2 py-0.5 text-xs font-medium">{contract.status}</span>
                </div>
                <div className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                  <span className="text-black">Предмет: {contract.subject}</span>
                  <span className="text-black">Цена: {formatMoney(contract.price, contract.currency)}</span>
                  <span className="text-black">Срок исполнения: {contract.execution_period}</span>
                  <span className="text-black">Ответственный: {contract.responsible_person}</span>
                  <span className="text-black">Этап: {contract.execution_stage}</span>
                  <span className="text-black">
                    Стороны: {contract.parties.customer.company_name} → {contract.parties.supplier.company_name}
                  </span>
                </div>
                {(contract.documents ?? []).length > 0 && <DocumentList documents={contract.documents} />}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Documents ---------------------------------------------------------------- */}
      <Section title={`Документы (${profile.documents.length})`}>
        <DocumentList documents={profile.documents} />
      </Section>
    </div>
  )
}
