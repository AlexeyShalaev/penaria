import {Archive, ArchiveRestore, Check, Lock, MoveRight, Pencil, Plus, SearchX, Users} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useParams} from 'react-router'

import {AddEntityDialog} from '@/features/create-entity'
import {ArchiveEntityDialog} from '@/features/archive-entity'
import {EditEntityDialog} from '@/features/edit-entity'
import {MoveEntityDialog} from '@/features/move-entity'
import {
  childKinds,
  type EntityDetail,
  EntityTree,
  FreshnessBadge,
  KIND_ICON,
  type Status,
  useEntity,
  useRestoreEntity,
  useVerifyEntity,
} from '@/entities/entity'
import {describeError, isApiError} from '@/shared/api'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Badge, Breadcrumbs, Button, Card, Empty, ErrorState, IconTile, Loading, Tabs, type Tone} from '@/shared/ui'

import styles from './EntityPage.module.css'
import {History} from './History'

const STATUS_TONE: Record<Status, Tone> = {present: 'neutral', missing: 'danger', lent: 'info', in_repair: 'warn'}

type Dialog = 'add' | 'edit' | 'move' | 'archive'

export function EntityPage() {
  const {t} = useTranslation()
  const {entityId = ''} = useParams<{entityId: string}>()
  const entity = useEntity(entityId)

  if (entity.isPending) return <Loading label={t('common.loading')} />
  if (entity.isError) {
    if (isApiError(entity.error, 'entity_not_found')) {
      return (
        <Empty
          icon={SearchX}
          title={t('entity.notFoundTitle')}
          text={t('entity.notFoundText')}
          action={<Link to="/">{t('notFound.home')}</Link>}
        />
      )
    }
    return (
      <ErrorState
        message={describeError(entity.error, t)}
        retryLabel={t('common.retry')}
        onRetry={() => void entity.refetch()}
      />
    )
  }
  // A new entity id starts with its own tabs and no dialog open.
  return <EntityView key={entity.data.id} entity={entity.data} />
}

function EntityView({entity}: {entity: EntityDetail}) {
  const {t, i18n} = useTranslation()
  const [tab, setTab] = useState<'contents' | 'history'>('contents')
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const verify = useVerifyEntity(entity.id)
  const restore = useRestoreEntity(entity.id)
  const archived = entity.archived_at !== null
  const editable = entity.can_edit && !archived
  const canAddInside = editable && childKinds(entity.kind).length > 0
  const close = () => setDialog(null)
  const actionError = verify.error ?? restore.error

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })

  return (
    <>
      <Breadcrumbs
        label={t('entity.breadcrumbs')}
        items={[
          {label: t('shell.places'), to: `/homes/${entity.home_id}/places`},
          ...entity.path.map((place) => ({label: place.name, to: `/entities/${place.id}`})),
        ]}
      />

      <div className={styles.columns}>
        <div className={styles.mainColumn}>
          <header className={styles.hero}>
            <IconTile icon={KIND_ICON[entity.kind]} size="lg" accent />
            <div className={styles.heroText}>
              <span className={styles.kind}>{t(`kinds.${entity.kind}`)}</span>
              <h1 className={styles.title}>{entity.name}</h1>
              <div className={styles.badges}>
                <FreshnessBadge freshness={entity.freshness} verifiedAt={entity.verified_at} />
                <Badge tone={STATUS_TONE[entity.status]}>{t(`status.${entity.status}`)}</Badge>
                {entity.quantity !== null && (
                  <Badge>
                    {entity.unit
                      ? `${formatNumber(entity.quantity, i18n.language)} ${entity.unit}`
                      : t('entity.pieces', {
                          count: Number(entity.quantity),
                          formatted: formatNumber(entity.quantity, i18n.language),
                        })}
                  </Badge>
                )}
                {entity.privacy === 'private' && <Badge icon={Lock}>{t('privacy.private')}</Badge>}
                {entity.privacy === 'guest_visible' && <Badge icon={Users}>{t('privacy.guest_visible')}</Badge>}
                {archived && <Badge tone="warn">{t('entity.archived')}</Badge>}
              </div>
              {entity.aliases.length > 0 && (
                <p className={styles.aliases}>{t('entity.aliases', {aliases: entity.aliases.join(', ')})}</p>
              )}
            </div>
          </header>

          {entity.archived_at !== null && (
            <p className={styles.notice}>
              {t('entity.archivedNotice', {when: formatRelative(new Date(entity.archived_at), i18n.language)})}
              {entity.archive_reason && ` ${t(`archiveReason.${entity.archive_reason}`)}.`}
            </p>
          )}
          {!entity.can_edit && <p className={styles.notice}>{t('entity.readOnly')}</p>}

          {entity.can_edit && (
            <div className={styles.actions}>
              {archived ? (
                <Button
                  icon={ArchiveRestore}
                  disabled={restore.isPending}
                  onClick={() => restore.mutate({version: entity.version})}
                >
                  {t('actions.restore')}
                </Button>
              ) : (
                <>
                  <Button icon={Check} disabled={verify.isPending} onClick={() => verify.mutate(undefined)}>
                    {t('actions.verify')}
                  </Button>
                  {entity.kind !== 'property' && (
                    <Button variant="secondary" icon={MoveRight} onClick={() => setDialog('move')}>
                      {t('actions.move')}
                    </Button>
                  )}
                  <Button variant="ghost" icon={Pencil} onClick={() => setDialog('edit')}>
                    {t('actions.edit')}
                  </Button>
                  <Button variant="ghost" icon={Archive} onClick={() => setDialog('archive')}>
                    {t('actions.archive')}
                  </Button>
                </>
              )}
            </div>
          )}
          {actionError && <ErrorState message={describeError(actionError, t)} />}

          <Tabs
            label={t('entity.sections')}
            value={tab}
            onChange={setTab}
            options={[
              {value: 'contents', label: t('entity.contents', {count: entity.children})},
              {value: 'history', label: t('entity.history')},
            ]}
          />

          {tab === 'contents' ? (
            <section className={styles.section} aria-label={t('entity.contents', {count: entity.children})}>
              {canAddInside && (
                <div className={styles.sectionActions}>
                  <Button size="sm" variant="secondary" icon={Plus} onClick={() => setDialog('add')}>
                    {t('actions.addInside')}
                  </Button>
                </div>
              )}
              <Card padded={false}>
                <EntityTree
                  homeId={entity.home_id}
                  parentId={entity.id}
                  expanded={expanded}
                  onToggle={toggle}
                  empty={<p className={styles.emptyContents}>{t('entity.nothingInside')}</p>}
                />
              </Card>
            </section>
          ) : (
            <History entityId={entity.id} />
          )}
        </div>

        <Card as="section" className={styles.aside} aria-label={t('entity.where')}>
          <h2 className={styles.cardTitle}>{t('entity.where')}</h2>
          <p className={styles.path}>
            {entity.path.length ? entity.path.map((place) => place.name).join(' → ') : t('picker.top')}
          </p>
          <dl className={styles.facts}>
            <dt>{t('fields.kind')}</dt>
            <dd>{t(`kinds.${entity.kind}`)}</dd>
            <dt>{t('fields.status')}</dt>
            <dd>{t(`status.${entity.status}`)}</dd>
            <dt>{t('fields.privacy')}</dt>
            <dd>{t(`privacy.${entity.privacy}`)}</dd>
            <dt>{t('entity.lastChecked')}</dt>
            <dd>
              {entity.verified_at
                ? formatDateTime(new Date(entity.verified_at), i18n.language)
                : t('entity.neverChecked')}
            </dd>
          </dl>
        </Card>
      </div>

      {dialog === 'add' && (
        <AddEntityDialog
          homeId={entity.home_id}
          parent={{id: entity.id, kind: entity.kind, name: entity.name}}
          onClose={close}
          onCreated={() => {
            close()
            setTab('contents')
          }}
        />
      )}
      {dialog === 'edit' && <EditEntityDialog entity={entity} onClose={close} />}
      {dialog === 'move' && <MoveEntityDialog entity={entity} onClose={close} />}
      {dialog === 'archive' && <ArchiveEntityDialog entity={entity} onClose={close} />}
    </>
  )
}

function formatNumber(value: string, language: string): string {
  return new Intl.NumberFormat(language, {maximumFractionDigits: 3}).format(Number(value))
}
