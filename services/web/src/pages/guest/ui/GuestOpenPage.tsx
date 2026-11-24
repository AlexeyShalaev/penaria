import {DoorOpen} from 'lucide-react'
import {useEffect, useRef} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useNavigate, useParams} from 'react-router'

import {useAccount, useSignOut} from '@/entities/account'
import {useOpenGuestLink} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, Card, IconTile, Loading, PageTitle} from '@/shared/ui'

import styles from './GuestPage.module.css'

/**
 * Where a guest link leads: it exchanges the link's token for a guest session in this browser, then
 * shows the visit at `/guest`, so the token does not stay in the address bar. A browser signed in to
 * an account asks first: a guest session takes the account's place in it.
 */
export function GuestOpenPage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const {token = ''} = useParams<{token: string}>()
  const account = useAccount()
  const open = useOpenGuestLink()
  const signOut = useSignOut()
  const started = useRef(false)

  const start = () => {
    started.current = true
    open.mutate(token, {onSuccess: () => navigate('/guest', {replace: true})})
  }

  useEffect(() => {
    if (account.isSuccess && account.data === null && !started.current) start()
  })

  if (account.data) {
    return (
      <main className={styles.narrow}>
        <IconTile icon={DoorOpen} size="lg" accent />
        <PageTitle>{t('guest.signedInTitle')}</PageTitle>
        <p className={styles.muted}>{t('guest.signedInText', {name: account.data.display_name})}</p>
        <div className={styles.buttons}>
          <Button disabled={signOut.isPending} onClick={() => signOut.mutate(undefined, {onSuccess: start})}>
            {t('guest.continue')}
          </Button>
          <Link to="/">{t('guest.stay')}</Link>
        </div>
      </main>
    )
  }
  return (
    <main className={styles.narrow}>
      {open.isError || account.isError ? (
        <Card className={styles.ended}>
          <IconTile icon={DoorOpen} size="lg" />
          <PageTitle>{t('guest.cannotOpen')}</PageTitle>
          <p className={styles.muted}>{describeError(open.error ?? account.error, t)}</p>
        </Card>
      ) : (
        <Loading label={t('guest.opening')} />
      )}
    </main>
  )
}
