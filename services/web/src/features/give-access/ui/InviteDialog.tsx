import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {useMailEnabled} from '@/entities/install'
import {placeLabel, type Role, roleName, RolePicker, ShareLink, useCreateInvitation, useRoles} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Button, Chip, Dialog, Field, FormActions, FormError, FormLayout, QueryState, TextInput} from '@/shared/ui'

import {daysFrom, defaultDays, endOfDay, toDateInput} from '../model/dates'
import styles from './AccessDialog.module.css'
import {ExpiryField} from './ExpiryField'
import {ScopeField} from './ScopeField'

const LINK_DAYS = [1, 7, 30] as const

/** Invites a person into the home with a role, as a link and a QR code to pass on. */
export function InviteDialog(props: {homeId: string; owner: boolean; onClose: () => void}) {
  const {t} = useTranslation()
  const roles = useRoles(props.homeId)
  return (
    <Dialog title={t('invite.title')} closeLabel={t('common.close')} onClose={props.onClose}>
      <QueryState query={roles}>
        {(list) => (
          <InviteForm
            homeId={props.homeId}
            roles={list.filter((role) => role.preset !== 'owner' || props.owner)}
            onClose={props.onClose}
          />
        )}
      </QueryState>
    </Dialog>
  )
}

function InviteForm(props: {homeId: string; roles: Role[]; onClose: () => void}) {
  const {t, i18n} = useTranslation()
  const create = useCreateInvitation(props.homeId)
  const recent = useRecentSignIn()
  const [role, setRole] = useState(() => props.roles.find((r) => r.preset === 'family') ?? props.roles[0])
  const [whole, setWhole] = useState(true)
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [linkDays, setLinkDays] = useState<number>(7)
  const [ends, setEnds] = useState('')
  const [transfer, setTransfer] = useState(false)
  const [email, setEmail] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const mail = useMailEnabled()
  const owner = role?.preset === 'owner'

  const pickRole = (picked: Role) => {
    setRole(picked)
    setTransfer(false)
    const days = defaultDays(picked.default_duration_seconds)
    setEnds(picked.expiry_required && days ? toDateInput(daysFrom(new Date(), days)) : '')
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!role) return
    const missingPlace = !owner && !whole && !placeId
    setProblem(missingPlace ? t('people.pickPlace') : null)
    if (missingPlace) return
    const body = {
      role_id: role.id,
      scope_entity_id: owner || whole ? null : placeId,
      valid_days: linkDays,
      grant_expires_at: owner || !ends ? null : endOfDay(ends),
      leave_when_accepted: owner && transfer,
      ...(email.trim() ? {email: email.trim()} : {}),
    }
    const send = () => create.mutate(body, {onError: recent.retryOnError(send)})
    send()
  }

  if (create.data) {
    const {invitation, url, emailed_to: emailedTo} = create.data
    return (
      <FormLayout>
        {emailedTo && (
          <p role="status" className={styles.emailed}>
            {t('invite.emailed', {email: emailedTo})}
          </p>
        )}
        <p className={styles.text}>
          {t(invitation.scope ? 'invite.readyPlace' : 'invite.readyWhole', {
            role: roleName(invitation.role, t),
            place: invitation.scope && placeLabel(invitation.scope.names),
            until: formatDateTime(new Date(invitation.expires_at), i18n.language),
          })}
        </p>
        <ShareLink url={url} title={t('invite.title')} />
        <FormActions>
          <Button onClick={props.onClose}>{t('common.done')}</Button>
        </FormActions>
      </FormLayout>
    )
  }

  const error = problem ?? (recent.errorToShow(create.error) ? describeError(create.error, t) : null)
  return (
    <>
      <form onSubmit={submit}>
        <FormLayout>
          <RolePicker label={t('people.role')} roles={props.roles} value={role?.id ?? null} onChange={pickRole} />
          {owner ? (
            <label className={styles.check}>
              <input type="checkbox" checked={transfer} onChange={(event) => setTransfer(event.target.checked)} />
              <span>
                <span className={styles.checkTitle}>{t('invite.transfer')}</span>
                <span className={styles.checkHint}>{t('invite.transferHint')}</span>
              </span>
            </label>
          ) : (
            <>
              <ScopeField
                homeId={props.homeId}
                whole={whole}
                onWholeChange={setWhole}
                value={placeId}
                onChange={setPlaceId}
              />
              <ExpiryField
                label={t('people.ends')}
                value={ends}
                onChange={setEnds}
                required={!!role?.expiry_required}
              />
            </>
          )}
          <fieldset className={styles.group}>
            <legend className={styles.legend}>{t('invite.linkWorks')}</legend>
            <div className={styles.chips} role="radiogroup" aria-label={t('invite.linkWorks')}>
              {LINK_DAYS.map((days) => (
                <Chip key={days} role="radio" aria-checked={linkDays === days} onClick={() => setLinkDays(days)}>
                  {t('people.days', {count: days})}
                </Chip>
              ))}
            </div>
          </fieldset>
          {mail.data && (
            <Field label={t('invite.email')} hint={t('invite.emailHint')}>
              <TextInput
                type="email"
                inputMode="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="off"
              />
            </Field>
          )}
          {error && <FormError>{error}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={props.onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {t('invite.submit')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
      {recent.dialog}
    </>
  )
}
