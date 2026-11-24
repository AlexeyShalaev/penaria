import {Check, ChevronDown, ChevronRight, Lock, Users} from 'lucide-react'
import type {CSSProperties, ReactNode} from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router'

import {describeError} from '@/shared/api'
import {Badge, ErrorState, IconTile, Loading} from '@/shared/ui'

import {type EntitySummary, useChildren} from '../api/entities'
import {KIND_ICON, STRUCTURAL_KINDS} from '../model/kinds'
import styles from './EntityTree.module.css'

export type TreeSelection = {
  selectedId: string | null
  canSelect: (entity: EntitySummary) => boolean
  onSelect: (entity: EntitySummary) => void
}

type Props = {
  homeId: string
  /** The entity whose contents to show; the tops of the home when null. */
  parentId?: string | null
  includeArchived?: boolean
  expanded: ReadonlySet<string>
  onToggle: (entityId: string) => void
  /** Rows pick a place instead of opening it. */
  select?: TreeSelection
  /** Left out with everything inside it, such as the entity being moved. */
  hiddenId?: string
  empty?: ReactNode
}

/** The home tree, loading the contents of each place when it is expanded. */
export function EntityTree(props: Props) {
  return (
    <ul className={styles.tree}>
      <Level {...props} parentId={props.parentId ?? null} depth={0} />
    </ul>
  )
}

function Level(props: Props & {parentId: string | null; depth: number}) {
  const {t} = useTranslation()
  const children = useChildren(props.homeId, props.parentId, props.includeArchived)
  const indent = {'--depth': props.depth} as CSSProperties

  if (children.isPending) {
    return (
      <li className={styles.note} style={indent}>
        <Loading label={t('common.loading')} />
      </li>
    )
  }
  if (children.isError) {
    return (
      <li className={styles.note} style={indent}>
        <ErrorState
          message={describeError(children.error, t)}
          retryLabel={t('common.retry')}
          onRetry={() => void children.refetch()}
        />
      </li>
    )
  }
  const visible = children.data.filter((entity) => entity.id !== props.hiddenId)
  if (visible.length === 0 && props.depth === 0 && props.empty) return <li>{props.empty}</li>
  return visible.map((entity) => <Row key={entity.id} {...props} entity={entity} />)
}

function Row(props: Props & {entity: EntitySummary; depth: number}) {
  const {t} = useTranslation()
  const {entity, depth, select} = props
  const open = props.expanded.has(entity.id)
  const selected = select?.selectedId === entity.id
  const content = (
    <>
      <IconTile icon={KIND_ICON[entity.kind]} size="sm" accent={entity.kind === 'property'} />
      <span className={styles.text}>
        <span className={STRUCTURAL_KINDS.has(entity.kind) ? styles.strongName : styles.name}>{entity.name}</span>
        <span className={styles.subtitle}>
          {t(`kinds.${entity.kind}`)}
          {entity.children > 0 && ` · ${t('tree.inside', {count: entity.children})}`}
        </span>
      </span>
      {entity.privacy === 'private' && <Lock className={styles.marker} role="img" aria-label={t('privacy.private')} />}
      {entity.privacy === 'guest_visible' && (
        <Users className={styles.marker} role="img" aria-label={t('privacy.guest_visible')} />
      )}
      {entity.archived_at !== null && <Badge>{t('entity.archived')}</Badge>}
      {select ? (
        selected && <Check className={styles.check} aria-hidden />
      ) : (
        <ChevronRight className={styles.chevron} aria-hidden />
      )}
    </>
  )
  return (
    <li>
      <div
        className={[styles.row, entity.archived_at !== null && styles.archived].filter(Boolean).join(' ')}
        style={{'--depth': depth} as CSSProperties}
      >
        <span className={styles.toggleSlot}>
          {entity.children > 0 && (
            <button
              type="button"
              className={styles.toggle}
              aria-expanded={open}
              aria-label={t(open ? 'tree.collapse' : 'tree.expand', {name: entity.name})}
              onClick={() => props.onToggle(entity.id)}
            >
              {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
            </button>
          )}
        </span>
        {select ? (
          <button
            type="button"
            className={styles.main}
            aria-pressed={selected}
            disabled={!select.canSelect(entity)}
            onClick={() => select.onSelect(entity)}
          >
            {content}
          </button>
        ) : (
          <Link className={styles.main} to={`/entities/${entity.id}`}>
            {content}
          </Link>
        )}
      </div>
      {open && (
        <ul className={styles.tree}>
          <Level {...props} parentId={entity.id} depth={depth + 1} />
        </ul>
      )}
    </li>
  )
}
