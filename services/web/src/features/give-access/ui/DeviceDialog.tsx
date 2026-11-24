import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {type Role, RolePicker, useCreateDevice, useRoles} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, CopyButton, Dialog, Field, FormActions, FormError, FormLayout, QueryState, TextInput} from '@/shared/ui'

import styles from './AccessDialog.module.css'
import {ScopeField} from './ScopeField'

/** A role a device can hold: not an owner's, and not one whose access must end, since a device's never does. */
function fitsADevice(role: Role) {
  return role.preset !== 'owner' && !role.expiry_required
}

/** Adds a device or an integration: a name, a role and a place, then its token, shown once. */
export function DeviceDialog(props: {homeId: string; onClose: () => void}) {
  const {t} = useTranslation()
  const roles = useRoles(props.homeId)
  return (
    <Dialog title={t('device.title')} closeLabel={t('common.close')} onClose={props.onClose}>
      <QueryState query={roles}>
        {(list) => <DeviceForm homeId={props.homeId} roles={list.filter(fitsADevice)} onClose={props.onClose} />}
      </QueryState>
    </Dialog>
  )
}

function DeviceForm(props: {homeId: string; roles: Role[]; onClose: () => void}) {
  const {t} = useTranslation()
  const create = useCreateDevice(props.homeId)
  const recent = useRecentSignIn()
  const [name, setName] = useState('')
  const [role, setRole] = useState(() => props.roles.find((r) => r.preset === 'family') ?? props.roles[0])
  const [whole, setWhole] = useState(true)
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!role) return
    const missingPlace = !whole && !placeId
    setProblem(missingPlace ? t('people.pickPlace') : null)
    if (missingPlace) return
    const body = {name: name.trim(), role_id: role.id, scope_entity_id: whole ? null : placeId}
    const send = () => create.mutate(body, {onError: recent.retryOnError(send)})
    send()
  }

  if (create.data) {
    return (
      <FormLayout>
        <p className={styles.text}>{t('device.ready', {name: create.data.device.name})}</p>
        <TokenReady homeId={props.homeId} token={create.data.token} />
        <FormActions>
          <Button onClick={props.onClose}>{t('common.done')}</Button>
        </FormActions>
      </FormLayout>
    )
  }

  if (!role) return <p className={styles.text}>{t('device.noRole')}</p>
  const failure = recent.errorToShow(create.error)
  const error = problem ?? (failure ? describeError(failure, t) : null)
  return (
    <>
      <form onSubmit={submit}>
        <FormLayout>
          <p className={styles.text}>{t('device.text')}</p>
          <Field label={t('device.name')} hint={t('device.nameHint')}>
            <TextInput value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} />
          </Field>
          <RolePicker label={t('people.role')} roles={props.roles} value={role.id} onChange={setRole} />
          <ScopeField
            homeId={props.homeId}
            whole={whole}
            onWholeChange={setWhole}
            value={placeId}
            onChange={setPlaceId}
          />
          {error && <FormError>{error}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={props.onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {t('device.submit')}
            </Button>
          </FormActions>
        </FormLayout>
      </form>
      {recent.dialog}
    </>
  )
}

/** The new token, to copy now, and a command that tries it. */
function TokenReady(props: {homeId: string; token: string}) {
  const {t} = useTranslation()
  const example = `curl -H "Authorization: Bearer ${props.token}" ${window.location.origin}/api/v1/homes/${props.homeId}`
  return (
    <>
      <div className={styles.secret}>
        <input
          className={styles.code}
          value={props.token}
          readOnly
          aria-label={t('device.token')}
          onFocus={(event) => event.currentTarget.select()}
        />
        <CopyButton text={props.token} label={t('device.copy')} copiedLabel={t('share.copied')} />
      </div>
      <p className={styles.text}>{t('device.example')}</p>
      <pre className={styles.example} aria-label={t('device.exampleLabel')}>
        {example}
      </pre>
      <div>
        <CopyButton
          text={example}
          label={t('device.copyExample')}
          copiedLabel={t('share.copied')}
          variant="secondary"
        />
      </div>
    </>
  )
}
