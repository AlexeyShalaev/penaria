import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {placeLabel, type Role, RolePicker, ShareLink, useCreateGuestLink, useRoles} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Button, Chip, Dialog, Field, FormActions, FormError, FormLayout, QueryState, TextInput} from '@/shared/ui'

import {daysFrom, defaultDays, endOfDay, toDateInput} from '../model/dates'
import styles from './AccessDialog.module.css'
import {ScopeField} from './ScopeField'

const LINK_DAYS = [1, 3, 7] as const
type Length = (typeof LINK_DAYS)[number] | 'date'

/** Makes a guest link: no account needed, it shows what is marked for guests and ends on its own. */
export function GuestLinkDialog(props: {homeId: string; onClose: () => void}) {
  const {t} = useTranslation()
  const roles = useRoles(props.homeId)
  return (
    <Dialog title={t('guestLink.title')} closeLabel={t('common.close')} onClose={props.onClose}>
      <QueryState query={roles}>
        {(list) => (
          <GuestLinkForm homeId={props.homeId} roles={list.filter((role) => role.guest_view)} onClose={props.onClose} />
        )}
      </QueryState>
    </Dialog>
  )
}

function GuestLinkForm(props: {homeId: string; roles: Role[]; onClose: () => void}) {
  const {t, i18n} = useTranslation()
  const create = useCreateGuestLink(props.homeId)
  const [name, setName] = useState(() => t('guestLink.defaultName'))
  const [role, setRole] = useState(() => props.roles.find((r) => r.preset === 'guest') ?? props.roles[0])
  const [whole, setWhole] = useState(true)
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [length, setLength] = useState<Length>(
    () => (LINK_DAYS.find((days) => days === defaultDays(role?.default_duration_seconds)) ?? 3) as Length,
  )
  const [date, setDate] = useState(() => toDateInput(daysFrom(new Date(), 3)))
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!role) return
    const missingPlace = !whole && !placeId
    setProblem(missingPlace ? t('people.pickPlace') : null)
    if (missingPlace) return
    create.mutate({
      name: name.trim(),
      role_id: role.id,
      scope_entity_id: whole ? null : placeId,
      expires_at: length === 'date' ? endOfDay(date) : daysFrom(new Date(), length).toISOString(),
    })
  }

  if (create.data) {
    const {link, url} = create.data
    return (
      <FormLayout>
        <p className={styles.text}>
          {t('guestLink.ready', {
            where: link.scope ? placeLabel(link.scope.names) : t('people.wholeHome'),
            until: formatDateTime(new Date(link.expires_at), i18n.language),
          })}
        </p>
        <ShareLink url={url} title={link.name} />
        <FormActions>
          <Button onClick={props.onClose}>{t('common.done')}</Button>
        </FormActions>
      </FormLayout>
    )
  }

  if (!role) return <p className={styles.text}>{t('guestLink.noRole')}</p>
  const error = problem ?? (create.isError ? describeError(create.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
        <p className={styles.text}>{t('guestLink.text')}</p>
        <Field label={t('guestLink.name')} hint={t('guestLink.nameHint')}>
          <TextInput value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} />
        </Field>
        {props.roles.length > 1 && (
          <RolePicker label={t('people.role')} roles={props.roles} value={role.id} onChange={setRole} />
        )}
        <ScopeField
          homeId={props.homeId}
          whole={whole}
          onWholeChange={setWhole}
          value={placeId}
          onChange={setPlaceId}
        />
        <fieldset className={styles.group}>
          <legend className={styles.legend}>{t('guestLink.lasts')}</legend>
          <div className={styles.chips} role="radiogroup" aria-label={t('guestLink.lasts')}>
            {LINK_DAYS.map((days) => (
              <Chip key={days} role="radio" aria-checked={length === days} onClick={() => setLength(days)}>
                {t('people.days', {count: days})}
              </Chip>
            ))}
            <Chip role="radio" aria-checked={length === 'date'} onClick={() => setLength('date')}>
              {t('guestLink.untilDate')}
            </Chip>
          </div>
          {length === 'date' && (
            <Field label={t('guestLink.lastDay')}>
              <TextInput
                type="date"
                value={date}
                min={toDateInput(new Date())}
                onChange={(event) => setDate(event.target.value)}
                required
              />
            </Field>
          )}
        </fieldset>
        {error && <FormError>{error}</FormError>}
        <FormActions>
          <Button variant="secondary" onClick={props.onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {t('guestLink.submit')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
