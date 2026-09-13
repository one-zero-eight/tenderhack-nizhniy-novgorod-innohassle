import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { FaBriefcase, FaEnvelope, FaFileLines, FaGlobe, FaPhone, FaUser } from 'react-icons/fa6'
import { useAuth } from '@/app/providers/auth-context'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Tabs, { type TabItem } from '@/components/ui/Tabs'
import { requireAuth } from '@/app/routes/-guards'
import { useProfile } from '@/hooks/useProfile'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { SchemaDocumentOut, SchemaProfileViewOut } from '@/api/types'

export const Route = createFileRoute('/profile/')({
  beforeLoad: requireAuth,
  component: ProfilePage,
})

type TabValue = 'profile' | 'procurements' | 'offers' | 'contracts' | 'documents'

/** A labeled value. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-gray text-[0.6875rem] font-semibold tracking-wide uppercase">{label}</dt>
      <dd className="text-black text-sm break-words">{children}</dd>
    </div>
  )
}

/** A white content card. */
function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('border-gray-blue bg-white border p-5', className)}>{children}</div>
}

/** Card heading with a brand accent bar. */
function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-black flex items-center gap-2 text-base font-bold">
      <span className="bg-red h-4 w-1 shrink-0" aria-hidden="true" />
      {children}
    </h2>
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

/** Initials for the avatar, e.g. «ТехноСфера Инжиниринг» → «ТИ». */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')
}

/** A status pill. */
const PILL_TONES = {
  neutral: 'bg-pale-blue text-main-blue',
  red: 'bg-red text-white',
  green: 'bg-green/10 text-green',
} as const

function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: keyof typeof PILL_TONES }) {
  return (
    <span className={cn('px-2 py-0.5 text-xs font-medium whitespace-nowrap', PILL_TONES[tone])}>{children}</span>
  )
}

/** A labeled value inside detail grids. */
function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex flex-col gap-0.5">
      <span className="text-gray text-[0.6875rem] tracking-wide uppercase">{label}</span>
      <span className="text-black text-xs">{children}</span>
    </span>
  )
}

/** A compact list of documents. */
function DocumentList({ documents }: { documents?: SchemaDocumentOut[] }) {
  const items = documents ?? []
  if (items.length === 0) return <p className="text-gray text-sm">Документов нет.</p>
  return (
    <ul className="border-gray-blue flex flex-col border">
      {items.map((doc) => (
        <li
          key={doc.id}
          className="border-gray-blue hover:bg-pale-blue/40 flex items-center justify-between gap-3 border-b px-3 py-2 text-sm transition-colors last:border-b-0"
        >
          <span className="flex min-w-0 items-center gap-2">
            <FaFileLines className="text-red size-3.5 shrink-0" />
            <span className="text-black truncate" title={doc.title}>
              {doc.title}
            </span>
          </span>
          <span className="text-gray shrink-0 text-xs">
            {doc.file_type} · {formatSize(doc.size_bytes)}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Empty state for a tab with no data. */
function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-gray py-6 text-center text-sm">{children}</p>
}

/* ------------------------------------------------------------------- tabs */

function ProfileInfoTab({ profile, login, name }: { profile: SchemaProfileViewOut; login: string; name: string }) {
  const { company } = profile
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="flex flex-col gap-5">
        <CardTitle>Учётная запись</CardTitle>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Field label="Отображаемое имя">{profile.display_name || name || '—'}</Field>
          <Field label="Логин">{login}</Field>
          <Field label="Роль">{profile.type_label}</Field>
          <Field label="Руководитель">{company.ceo}</Field>
        </dl>

        <div className="border-gray-blue flex flex-col gap-2 border-t pt-4">
          <span className="text-gray text-[0.6875rem] font-semibold tracking-wide uppercase">Контакты</span>
          <a href={`tel:${company.phone}`} className="text-main-blue flex items-center gap-2 text-sm no-underline hover:underline">
            <FaPhone className="size-3 shrink-0" />
            {company.phone}
          </a>
          <a href={`mailto:${company.email}`} className="text-main-blue flex items-center gap-2 text-sm no-underline hover:underline">
            <FaEnvelope className="size-3 shrink-0" />
            {company.email}
          </a>
          {company.website && (
            <a
              href={company.website}
              target="_blank"
              rel="noopener noreferrer"
              className="text-main-blue flex items-center gap-2 text-sm no-underline hover:underline"
            >
              <FaGlobe className="size-3 shrink-0" />
              {company.website}
            </a>
          )}
        </div>
      </Card>

      <Card className="flex flex-col gap-4">
        <CardTitle>Организация</CardTitle>
        <div className="flex items-start gap-3">
          <FaBriefcase className="text-red mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-black text-sm font-bold break-words">{company.name}</span>
            {company.full_name && company.full_name !== company.name && (
              <span className="text-gray text-xs break-words">{company.full_name}</span>
            )}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-3">
          <Field label="ИНН">{company.inn}</Field>
          <Field label="КПП">{company.kpp}</Field>
          <Field label="ОГРН">{company.ogrn}</Field>
          <Field label="Роль">{company.role_label}</Field>
        </dl>
        <Field label="Адрес">{company.address}</Field>
      </Card>
    </div>
  )
}

function ProcurementsTab({ profile }: { profile: SchemaProfileViewOut }) {
  if (profile.procurements.length === 0) return <Empty>Закупок нет.</Empty>
  return (
    <div className="flex flex-col gap-4">
      {profile.procurements.map((procurement) => (
        <Card key={procurement.id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <span className="text-black min-w-0 text-base font-bold break-words">{procurement.title}</span>
            <Pill>{procurement.status}</Pill>
          </div>
          <dl className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Номер">{procurement.number}</Detail>
            <Detail label="Начальная цена">{formatMoney(procurement.initial_price, procurement.currency)}</Detail>
            <Detail label="Предложений">{procurement.offers_count}</Detail>
            <Detail label="Заказчик">
              {procurement.customer_name} · ИНН {procurement.customer_inn}
            </Detail>
            <Detail label="Опубликовано">{formatDateTime(procurement.published_at)}</Detail>
            <Detail label="Приём заявок до">{formatDateTime(procurement.submission_deadline)}</Detail>
          </dl>
          {(procurement.documents ?? []).length > 0 && (
            <div className="mt-4">
              <DocumentList documents={procurement.documents} />
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

function OffersTab({ profile }: { profile: SchemaProfileViewOut }) {
  if (profile.offers.length === 0) return <Empty>Предложений нет.</Empty>
  return (
    <div className="flex flex-col gap-4">
      {profile.offers.map((offer) => (
        <Card key={offer.id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <span className="text-black min-w-0 text-base font-bold break-words">{offer.procurement_title}</span>
            <span className="flex items-center gap-2">
              {offer.is_winner && <Pill tone="green">Победитель</Pill>}
              <Pill>{offer.status}</Pill>
            </span>
          </div>
          <dl className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Поставщик">
              {offer.supplier_name} · ИНН {offer.supplier_inn}
            </Detail>
            <Detail label="Цена">{formatMoney(offer.price)}</Detail>
            <Detail label="Подано">{formatDateTime(offer.submitted_at)}</Detail>
          </dl>
          {offer.details && <p className="text-black mt-3 text-sm break-words">{offer.details}</p>}
          {(offer.documents ?? []).length > 0 && (
            <div className="mt-4">
              <DocumentList documents={offer.documents} />
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

function ContractsTab({ profile }: { profile: SchemaProfileViewOut }) {
  if (profile.contracts.length === 0) return <Empty>Контрактов нет.</Empty>
  return (
    <div className="flex flex-col gap-4">
      {profile.contracts.map((contract) => (
        <Card key={contract.id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <Link
              to="/contracts/$contractId"
              params={{ contractId: contract.id }}
              className="text-black hover:text-main-blue min-w-0 text-base font-bold break-words no-underline transition-colors hover:underline"
            >
              {contract.title}
            </Link>
            <Pill>{contract.status}</Pill>
          </div>
          <dl className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Предмет">{contract.subject}</Detail>
            <Detail label="Цена">{formatMoney(contract.price, contract.currency)}</Detail>
            <Detail label="Срок исполнения">{contract.execution_period}</Detail>
            <Detail label="Ответственный">{contract.responsible_person}</Detail>
            <Detail label="Этап">{contract.execution_stage}</Detail>
            <Detail label="Заказчик">{contract.parties.customer.company_name}</Detail>
            <Detail label="Поставщик">{contract.parties.supplier.company_name}</Detail>
          </dl>
          {(contract.documents ?? []).length > 0 && (
            <div className="mt-4">
              <DocumentList documents={contract.documents} />
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

function DocumentsTab({ profile }: { profile: SchemaProfileViewOut }) {
  const companyDocs = profile.company.documents ?? []
  return (
    <div className="flex flex-col gap-5">
      {companyDocs.length > 0 && (
        <Card className="flex flex-col gap-3">
          <CardTitle>Документы организации</CardTitle>
          <DocumentList documents={companyDocs} />
        </Card>
      )}
      <Card className="flex flex-col gap-3">
        <CardTitle>Документы профиля</CardTitle>
        <DocumentList documents={profile.documents} />
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------------- page */

function ProfilePage() {
  const { user, isLoading: userLoading } = useAuth()
  const { data: profile, isLoading, isError, error, refetch } = useProfile()
  const [tab, setTab] = useState<TabValue>('profile')

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

  const name = profile.display_name || user.display_name || user.login
  const tabs: TabItem<TabValue>[] = [
    { value: 'profile', label: 'Профиль' },
    { value: 'procurements', label: 'Закупки', count: profile.procurements.length },
    { value: 'offers', label: 'Предложения', count: profile.offers.length },
    { value: 'contracts', label: 'Контракты', count: profile.contracts.length },
    { value: 'documents', label: 'Документы', count: profile.documents.length },
  ]

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      {/* Identity header: avatar square with initials, name and role badges. */}
      <header className="border-gray-blue bg-white flex flex-wrap items-center gap-5 border p-5">
        <span
          aria-hidden="true"
          className="bg-red flex size-16 shrink-0 items-center justify-center text-xl font-bold text-white"
        >
          {initials(name) || <FaUser />}
        </span>
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="text-black text-2xl font-bold break-words">{name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone="red">{profile.type_label}</Pill>
            <span className="text-gray text-sm">{user.login}</span>
          </div>
        </div>
      </header>

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === 'profile' && <ProfileInfoTab profile={profile} login={user.login} name={name} />}
      {tab === 'procurements' && <ProcurementsTab profile={profile} />}
      {tab === 'offers' && <OffersTab profile={profile} />}
      {tab === 'contracts' && <ContractsTab profile={profile} />}
      {tab === 'documents' && <DocumentsTab profile={profile} />}
    </div>
  )
}
