import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {ShareLink, useCreateResetLink} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Button, Dialog, FormActions, FormError, FormLayout} from '@/shared/ui'

import styles from './ResetLinkDialog.module.css'

/** A password reset link for a member who cannot sign in, to pass on by hand; it works for 24 hours. */
export function ResetLinkDialog(props: {homeId: string; userId: string; name: string; onClose: () => void}) {
  const {t, i18n} = useTranslation()
  const create = useCreateResetLink(props.homeId)
  const recent = useRecentSignIn()
  const make = () => {
    const send = () => create.mutate(props.userId, {onError: recent.retryOnError(send)})
    send()
  }
  const error = recent.errorToShow(create.error)

  return (
    <>
      <Dialog title={t('resetLink.title', {name: props.name})} closeLabel={t('common.close')} onClose={props.onClose}>
        {create.data ? (
          <FormLayout>
            <p className={styles.text}>
              {t('resetLink.ready', {
                name: props.name,
                until: formatDateTime(new Date(create.data.expires_at), i18n.language),
              })}
            </p>
            <ShareLink url={create.data.url} title={t('resetLink.shareTitle')} />
            <FormActions>
              <Button onClick={props.onClose}>{t('common.done')}</Button>
            </FormActions>
          </FormLayout>
        ) : (
          <FormLayout>
            <p className={styles.text}>{t('resetLink.text', {name: props.name})}</p>
            {error && <FormError>{describeError(error, t)}</FormError>}
            <FormActions>
              <Button variant="secondary" onClick={props.onClose}>
                {t('common.cancel')}
              </Button>
              <Button disabled={create.isPending} onClick={make}>
                {t('resetLink.make')}
              </Button>
            </FormActions>
          </FormLayout>
        )}
      </Dialog>
      {recent.dialog}
    </>
  )
}
