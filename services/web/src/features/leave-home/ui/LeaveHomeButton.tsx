import {LogOut} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useRecentSignIn} from '@/entities/account'
import {useLeaveHome} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, Dialog, FormActions, FormError, FormLayout} from '@/shared/ui'

import styles from './LeaveHomeButton.module.css'

/** Gives up the signed-in person's access to the home, after asking; the last owner is refused. */
export function LeaveHomeButton(props: {homeId: string; homeName: string; onLeft: () => void}) {
  const {t} = useTranslation()
  const leave = useLeaveHome(props.homeId)
  const recent = useRecentSignIn()
  const [asking, setAsking] = useState(false)

  const confirm = () => {
    const send = () => leave.mutate(undefined, {onSuccess: props.onLeft, onError: recent.retryOnError(send)})
    send()
  }
  const error = recent.errorToShow(leave.error)

  return (
    <>
      <Button variant="secondary" icon={LogOut} onClick={() => setAsking(true)}>
        {t('people.leave')}
      </Button>
      {asking && (
        <Dialog
          title={t('people.leaveTitle', {home: props.homeName})}
          closeLabel={t('common.close')}
          onClose={() => setAsking(false)}
        >
          <FormLayout>
            <p className={styles.text}>{t('people.leaveText')}</p>
            {error && <FormError>{describeError(error, t)}</FormError>}
            <FormActions>
              <Button variant="secondary" onClick={() => setAsking(false)}>
                {t('common.cancel')}
              </Button>
              <Button variant="danger" disabled={leave.isPending} onClick={confirm}>
                {t('people.leave')}
              </Button>
            </FormActions>
          </FormLayout>
        </Dialog>
      )}
      {recent.dialog}
    </>
  )
}
