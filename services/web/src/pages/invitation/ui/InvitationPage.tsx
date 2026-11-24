import {Clock, DoorOpen, MapPin} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {Link, useNavigate, useParams} from 'react-router'

import {NewAccountForm} from '@/features/accept-invitation'
import {SecondFactorForm, SignInForm} from '@/features/sign-in'
import {type SecondFactorChallenge, useAccount, useSignOut} from '@/entities/account'
import {useHomesChanged} from '@/entities/home'
import {
  type InvitationPreview,
  placeLabel,
  RoleBadge,
  roleDescription,
  useAcceptInvitation,
  useInvitationPreview,
} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Badge, Button, Card, FormError, IconTile, PageTitle, QueryState, Tabs} from '@/shared/ui'

import styles from './InvitationPage.module.css'

/** Where an invitation's link leads: what it offers, then accepting it with an account, new or existing. */
export function InvitationPage() {
  const {t} = useTranslation()
  const {token = ''} = useParams<{token: string}>()
  const preview = useInvitationPreview(token)
  const account = useAccount()

  return (
    <main className={styles.page}>
      <QueryState query={preview}>
        {(invitation) => (
          <>
            <Offer invitation={invitation} />
            <Card className={styles.card}>
              <QueryState query={account}>
                {(signedIn) =>
                  signedIn ? <Accept token={token} name={signedIn.display_name} /> : <SignInOrCreate token={token} />
                }
              </QueryState>
            </Card>
          </>
        )}
      </QueryState>
      {preview.isError && (
        <p className={styles.back}>
          <Link to="/">{t('invitation.toStart')}</Link>
        </p>
      )}
    </main>
  )
}

function Offer(props: {invitation: InvitationPreview}) {
  const {t, i18n} = useTranslation()
  const {invitation} = props
  const description = roleDescription(invitation.role, t)
  return (
    <div className={styles.intro}>
      <IconTile icon={DoorOpen} size="lg" accent />
      <PageTitle>{t('invitation.title', {name: invitation.inviter, home: invitation.home.name})}</PageTitle>
      <div className={styles.facts}>
        <RoleBadge role={invitation.role} />
        <Badge icon={MapPin}>
          {invitation.scope ? t('invitation.only', {place: placeLabel(invitation.scope.names)}) : t('people.wholeHome')}
        </Badge>
        {invitation.grant_expires_at && (
          <Badge icon={Clock}>
            {t('people.until', {when: formatDateTime(new Date(invitation.grant_expires_at), i18n.language)})}
          </Badge>
        )}
      </div>
      {description && <p className={styles.text}>{description}</p>}
      {invitation.leave_when_accepted && (
        <p className={styles.transfer}>{t('invitation.transfer', {name: invitation.inviter})}</p>
      )}
    </div>
  )
}

function Accept(props: {token: string; name: string}) {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const accept = useAcceptInvitation(props.token)
  const homesChanged = useHomesChanged()
  const signOut = useSignOut()
  const joined = async (homeId: string) => {
    await homesChanged()
    navigate(`/homes/${homeId}/places`)
  }
  return (
    <div className={styles.accept}>
      <p className={styles.text}>{t('invitation.signedInAs', {name: props.name})}</p>
      {accept.isError && <FormError>{describeError(accept.error, t)}</FormError>}
      <Button
        disabled={accept.isPending}
        onClick={() => accept.mutate(undefined, {onSuccess: (home) => void joined(home.id)})}
      >
        {t('invitation.accept')}
      </Button>
      <Button variant="ghost" size="sm" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        {t('invitation.notYou')}
      </Button>
    </div>
  )
}

function SignInOrCreate(props: {token: string}) {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [challenge, setChallenge] = useState<SecondFactorChallenge | null>(null)
  return (
    <div className={styles.accept}>
      <Tabs
        label={t('invitation.how')}
        value={mode}
        options={[
          {value: 'new', label: t('invitation.newAccount')},
          {value: 'existing', label: t('invitation.haveAccount')},
        ]}
        onChange={setMode}
      />
      {mode === 'new' ? (
        <>
          <p className={styles.text}>{t('invitation.newAccountText')}</p>
          <NewAccountForm token={props.token} onJoined={(homeId) => navigate(`/homes/${homeId}/places`)} />
        </>
      ) : (
        <>
          <p className={styles.text}>{t('invitation.haveAccountText')}</p>
          {/* Signed in, the page offers to accept with that account. */}
          {challenge ? (
            <SecondFactorForm challenge={challenge} onSignedIn={() => undefined} onBack={() => setChallenge(null)} />
          ) : (
            <SignInForm onSignedIn={() => undefined} onSecondFactor={setChallenge} />
          )}
        </>
      )}
    </div>
  )
}
