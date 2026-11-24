import type {TFunction} from 'i18next'

import type {EntityEvent} from '@/entities/entity'

type Place = {name: string}
type Change = {from: unknown; to: unknown}

function place(value: unknown): Place | null {
  return typeof value === 'object' && value !== null && 'name' in value ? (value as Place) : null
}

function change(value: unknown): Change | null {
  return typeof value === 'object' && value !== null && 'to' in value ? (value as Change) : null
}

const text = (value: unknown) => (value === null || value === undefined ? '' : String(value))

/** The event as sentences a person reads, one per thing that changed. */
export function describeEvent(event: EntityEvent, t: TFunction): string[] {
  const {payload} = event
  switch (event.type) {
    case 'entity.created': {
      const parent = place(payload.parent)
      return [parent ? t('history.createdIn', {place: parent.name}) : t('history.created')]
    }
    case 'entity.moved': {
      const from = place(payload.from)
      const to = place(payload.to)
      if (from && to) return [t('history.moved', {from: from.name, to: to.name})]
      return [t('history.movedTo', {to: to?.name ?? ''})]
    }
    case 'entity.archived':
      return [t('history.archived', {reason: t(`archiveReason.${text(payload.reason)}`)})]
    case 'entity.restored':
      return [t('history.restored')]
    case 'entity.verified':
      return [t('history.verified')]
    case 'entity.updated':
      return Object.entries(payload).map(([field, value]) => describeChange(field, change(value), t))
    default:
      return [t('history.other')]
  }
}

function describeChange(field: string, value: Change | null, t: TFunction): string {
  if (value === null) return t('history.other')
  switch (field) {
    case 'name':
      return t('history.renamed', {from: text(value.from), to: text(value.to)})
    case 'aliases':
      return (value.to as string[]).length
        ? t('history.aliases', {to: (value.to as string[]).join(', ')})
        : t('history.aliasesCleared')
    case 'quantity':
    case 'unit':
      return value.to === null ? t(`history.${field}Cleared`) : t(`history.${field}`, {to: text(value.to)})
    case 'status':
    case 'privacy':
      return t(`history.${field}`, {
        from: t(`${field}.${text(value.from)}`),
        to: t(`${field}.${text(value.to)}`),
      })
    default:
      return t('history.other')
  }
}
