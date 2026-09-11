import Link from '@/components/ui/Link'
import { $api } from '@/api'
import { useLocation, useParams, useSearch } from '@tanstack/react-router'

const SEGMENT_LABELS: Record<string, string> = {
  edit: 'Редактирование контрактов',
  'pick-contracts': 'Выбор контрактов',
}

export default function Breadcrumbs() {
  const location = useLocation()
  const params = useParams({ strict: false })
  const search = useSearch({ strict: false }) as { entity?: string }
  const contractId = params.contract
  const entityId = search?.entity

  const { data: contractData } = $api.useQuery(
    'get',
    '/contracts/{contract_id}',
    {
      params: { path: { contract_id: Number(contractId) } },
    },
    { enabled: !!contractId && !isNaN(Number(contractId)) },
  )

  const pathname = location.pathname
  const isIndexPage = pathname === '/' || pathname === ''
  const isContractRoute = contractId && (pathname === `/${contractId}` || pathname === `/${contractId}/` || pathname.startsWith(`/${contractId}/`))

  if (isIndexPage) {
    return (
      <div className="mt-10 flex justify-center">
        <nav className="text-pale-black flex w-4xl items-start gap-2 text-sm">
          <span className="font-medium text-black">Закупки</span>
        </nav>
      </div>
    )
  }

  if (!isContractRoute) {
    return null
  }

  const contractName = contractData?.name ?? '...'
  const entities = (contractData as { entities?: Array<{ id?: string; query?: string }> })?.entities ?? []
  const currentEntity = entityId ? entities.find((e) => e.id === entityId) : null
  const entityLabel = currentEntity?.query ?? 'Позиции'
  const basePath = { to: '/$contract' as const, params: { contract: contractId } }

  const segments: { label: string; to?: { to: '/' | (typeof basePath)['to']; params?: Record<string, string> } }[] = []
  segments.push({ label: 'Закупки', to: { to: '/' } })
  segments.push({ label: contractName, to: basePath })
  segments.push({
    label: pathname.includes('/edit') ? entityLabel : entityLabel,
    to: pathname === `/${contractId}` || pathname === `/${contractId}/` ? undefined : basePath,
  })

  if (pathname.includes('/edit')) {
    segments.push({ label: SEGMENT_LABELS.edit })
  } else if (pathname.includes('/pick-contracts')) {
    segments.push({ label: SEGMENT_LABELS['pick-contracts'] })
  }

  return (
    <div className="mt-10 flex justify-center">
      <nav className="text-pale-black flex w-4xl min-w-0 items-start gap-2 text-sm">
        {segments.map((segment, i) => (
          <span key={i} className="flex min-w-0 items-center gap-2">
            {i > 0 && <span className="text-gray shrink-0">›</span>}
            {segment.to && i < segments.length - 1 ? (
              <Link to={segment.to.to} params={segment.to.params} className="hover:text-main-blue max-w-[100px] min-w-0 truncate" title={segment.label}>
                {segment.label}
              </Link>
            ) : (
              <span className="min-w-0 truncate font-medium text-black" title={segment.label}>
                {segment.label}
              </span>
            )}
          </span>
        ))}
      </nav>
    </div>
  )
}
