import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {type MemberGrant, type Role, RolePicker, useChangeGrant, useRoles} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, Dialog, FormActions, FormError, FormLayout, QueryState} from '@/shared/ui'

import {daysFrom, defaultDays, endOfDay, toDateInput} from '../model/dates'
import {ExpiryField} from './ExpiryField'
import {ScopeField} from './ScopeField'

/** Changes a member's role, place or end of access; the server asks for a recent sign-in. */
export function ChangeAccessDialog(props: {homeId: string; person: string; grant: MemberGrant; onClose: () => void}) {
  const {t} = useTranslation()
  const roles = useRoles(props.homeId)
  return (
    <Dialog
      title={t('changeAccess.title', {name: props.person})}
      closeLabel={t('common.close')}
      onClose={props.onClose}
    >
      <QueryState query={roles}>
        {(list) => <ChangeForm {...props} roles={list.filter((role) => role.preset !== 'owner')} />}
      </QueryState>
    </Dialog>
  )
}

function ChangeForm(props: {homeId: string; grant: MemberGrant; roles: Role[]; onClose: () => void}) {
  const {t} = useTranslation()
  const change = useChangeGrant(props.homeId)
  const recent = useRecentSignIn()
  const [role, setRole] = useState(() => props.roles.find((r) => r.id === props.grant.role.id) ?? props.roles[0])
  const [whole, setWhole] = useState(props.grant.scope === null)
  const [placeId, setPlaceId] = useState(props.grant.scope?.id ?? null)
  const [ends, setEnds] = useState(props.grant.expires_at ? toDateInput(new Date(props.grant.expires_at)) : '')
  const [problem, setProblem] = useState<string | null>(null)

  const pickRole = (picked: Role) => {
    setRole(picked)
    const days = defaultDays(picked.default_duration_seconds)
    if (picked.expiry_required && !ends && days) setEnds(toDateInput(daysFrom(new Date(), days)))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!role) return
    const missingPlace = !whole && !placeId
    setProblem(missingPlace ? t('people.pickPlace') : null)
    if (missingPlace) return
    const changes = {
      role_id: role.id,
      scope_entity_id: whole ? null : placeId,
      expires_at: ends ? endOfDay(ends) : null,
    }
    const send = () =>
      change.mutate({grantId: props.grant.id, changes}, {onSuccess: props.onClose, onError: recent.retryOnError(send)})
    send()
  }

  const error = problem ?? (recent.errorToShow(change.error) ? describeError(change.error, t) : null)
  return (
    <>
      <form onSubmit={submit}>
        <FormLayout>
          <RolePicker label={t('people.role')} roles={props.roles} value={role?.id ?? null} onChange={pickRole} />
          <ScopeField
            homeId={props.homeId}
            whole={whole}
            onWholeChange={setWhole}
            value={placeId}
            onChange={setPlaceId}
          />
          <ExpiryField label={t('people.ends')} value={ends} onChange={setEnds} required={!!role?.expiry_required} />
          {error && <FormError>{error}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={props.onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={change.isPending}>
              {t('common.save')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
      {recent.dialog}
    </>
  )
}
