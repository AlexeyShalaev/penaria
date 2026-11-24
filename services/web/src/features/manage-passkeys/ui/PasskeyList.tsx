import {KeyRound} from 'lucide-react'
import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {
  describePasskeyError,
  needsRecentSignIn,
  type Passkey,
  usePasskeys,
  useRecentSignIn,
  useRemovePasskey,
  useRenamePasskey,
} from '@/entities/account'
import {formatDateTime, formatRelative} from '@/shared/lib/time'
import {Button, Dialog, Field, FormActions, FormError, FormLayout, IconTile, QueryState, TextInput} from '@/shared/ui'

import styles from './PasskeyList.module.css'

/** The account's passkeys, each of which can be renamed or removed. */
export function PasskeyList() {
  const {t} = useTranslation()
  const passkeys = usePasskeys()
  const rename = useRenamePasskey()
  const remove = useRemovePasskey()
  const recent = useRecentSignIn()
  const [renaming, setRenaming] = useState<string | null>(null)
  const [removing, setRemoving] = useState<Passkey | null>(null)
  const failed = rename.error ?? (needsRecentSignIn(remove.error) ? null : remove.error)

  const removePasskey = (passkey: Passkey) =>
    remove.mutate(passkey.id, {onError: (error) => recent.retryAfterConfirming(error, () => removePasskey(passkey))})

  return (
    <QueryState query={passkeys}>
      {(list) => (
        <div className={styles.root}>
          {list.length === 0 ? (
            <p className={styles.empty}>{t('passkeys.empty')}</p>
          ) : (
            <ul className={styles.list}>
              {list.map((passkey) =>
                renaming === passkey.id ? (
                  <RenameRow
                    key={passkey.id}
                    passkey={passkey}
                    busy={rename.isPending}
                    onSave={(name) => rename.mutate({id: passkey.id, name}, {onSuccess: () => setRenaming(null)})}
                    onCancel={() => setRenaming(null)}
                  />
                ) : (
                  <PasskeyRow
                    key={passkey.id}
                    passkey={passkey}
                    busy={remove.isPending && remove.variables === passkey.id}
                    onRename={() => {
                      rename.reset()
                      setRenaming(passkey.id)
                    }}
                    onRemove={() => setRemoving(passkey)}
                  />
                ),
              )}
            </ul>
          )}
          {failed && <FormError>{describePasskeyError(failed, t)}</FormError>}
          {removing && (
            <RemoveDialog
              passkey={removing}
              onRemove={() => {
                setRemoving(null)
                removePasskey(removing)
              }}
              onClose={() => setRemoving(null)}
            />
          )}
          {recent.dialog}
        </div>
      )}
    </QueryState>
  )
}

function PasskeyRow(props: {passkey: Passkey; busy: boolean; onRename: () => void; onRemove: () => void}) {
  const {t, i18n} = useTranslation()
  const {passkey} = props
  const details = [
    t('passkeys.created', {when: formatDateTime(new Date(passkey.created_at), i18n.language)}),
    passkey.last_used_at
      ? t('passkeys.lastUsed', {when: formatRelative(new Date(passkey.last_used_at), i18n.language)})
      : t('passkeys.neverUsed'),
  ]
  return (
    <li className={styles.row}>
      <IconTile icon={KeyRound} size="sm" />
      <div className={styles.text}>
        <span className={styles.name}>{passkey.name}</span>
        <span className={styles.details}>{details.join(' · ')}</span>
      </div>
      <div className={styles.buttons}>
        <Button
          variant="ghost"
          size="sm"
          onClick={props.onRename}
          aria-label={t('passkeys.renameLabel', {name: passkey.name})}
        >
          {t('passkeys.rename')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={props.busy}
          onClick={props.onRemove}
          aria-label={t('passkeys.removeLabel', {name: passkey.name})}
        >
          {t('passkeys.remove')}
        </Button>
      </div>
    </li>
  )
}

function RenameRow(props: {passkey: Passkey; busy: boolean; onSave: (name: string) => void; onCancel: () => void}) {
  const {t} = useTranslation()
  const [name, setName] = useState(props.passkey.name)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    props.onSave(name.trim())
  }

  return (
    <li className={styles.row}>
      <form className={styles.rename} onSubmit={submit}>
        <Field label={t('passkeys.name')}>
          <TextInput value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required />
        </Field>
        <FormActions>
          <Button variant="secondary" size="sm" onClick={props.onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" size="sm" disabled={props.busy}>
            {t('common.save')}
          </Button>
        </FormActions>
      </form>
    </li>
  )
}

function RemoveDialog(props: {passkey: Passkey; onRemove: () => void; onClose: () => void}) {
  const {t} = useTranslation()
  return (
    <Dialog
      title={t('passkeys.removeTitle', {name: props.passkey.name})}
      closeLabel={t('common.close')}
      onClose={props.onClose}
    >
      <FormLayout>
        <p className={styles.dialogText}>{t('passkeys.removeText')}</p>
        <FormActions>
          <Button variant="secondary" onClick={props.onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="danger" onClick={props.onRemove}>
            {t('passkeys.remove')}
          </Button>
        </FormActions>
      </FormLayout>
    </Dialog>
  )
}
