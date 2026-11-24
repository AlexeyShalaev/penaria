import {Plus, QrCode, UserPlus} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'
import {useNavigate, useParams} from 'react-router'

import {DeviceDialog, GuestLinkDialog, InviteDialog} from '@/features/give-access'
import {LeaveHomeButton} from '@/features/leave-home'
import {canManagePeople, useHome, useHomesChanged} from '@/entities/home'
import {Button, Card, CardTitle, PageTitle, QueryState} from '@/shared/ui'

import {DeviceList} from './DeviceList'
import {GuestLinkList} from './GuestLinkList'
import {InvitationList} from './InvitationList'
import {MemberList} from './MemberList'
import styles from './PeoplePage.module.css'

/** Who has access to the home: its members, the invitations not yet accepted, the guest links and the devices. */
export function PeoplePage() {
  const {t} = useTranslation()
  const navigate = useNavigate()
  const {homeId = ''} = useParams<{homeId: string}>()
  const home = useHome(homeId)
  const [dialog, setDialog] = useState<'invite' | 'guest' | 'device' | null>(null)
  const homesChanged = useHomesChanged()
  const left = async () => {
    await homesChanged(homeId)
    navigate('/', {replace: true})
  }

  return (
    <QueryState query={home}>
      {(data) => {
        const manager = canManagePeople(data)
        const owner = !!data.access?.owner
        return (
          <div className={styles.page}>
            <header className={styles.header}>
              <PageTitle>{t('people.title')}</PageTitle>
              {manager && (
                <div className={styles.actions}>
                  <Button variant="secondary" icon={QrCode} onClick={() => setDialog('guest')}>
                    {t('people.guestLink')}
                  </Button>
                  <Button icon={UserPlus} onClick={() => setDialog('invite')}>
                    {t('people.invite')}
                  </Button>
                </div>
              )}
            </header>

            {manager ? (
              <div className={styles.columns}>
                <div className={styles.column}>
                  <Card as="section" aria-labelledby="people-members">
                    <CardTitle id="people-members">{t('people.members')}</CardTitle>
                    <MemberList homeId={homeId} owner={owner} />
                  </Card>
                  <Card as="section" aria-labelledby="people-invitations">
                    <CardTitle id="people-invitations">{t('people.invitations')}</CardTitle>
                    <InvitationList homeId={homeId} />
                  </Card>
                </div>
                <div className={styles.column}>
                  <Card as="section" aria-labelledby="people-guests">
                    <CardTitle id="people-guests">{t('people.guestLinks')}</CardTitle>
                    <p className={styles.text}>{t('people.guestLinksText')}</p>
                    <GuestLinkList homeId={homeId} />
                  </Card>
                  <Card as="section" aria-labelledby="people-devices">
                    <CardTitle id="people-devices">{t('people.devices')}</CardTitle>
                    <p className={styles.text}>{t('people.devicesText')}</p>
                    <DeviceList homeId={homeId} />
                    <div className={styles.cardActions}>
                      <Button variant="secondary" size="sm" icon={Plus} onClick={() => setDialog('device')}>
                        {t('people.addDevice')}
                      </Button>
                    </div>
                  </Card>
                </div>
              </div>
            ) : (
              <Card as="section" aria-labelledby="people-yours">
                <CardTitle id="people-yours">{t('people.yourAccess')}</CardTitle>
                <p className={styles.text}>{t('people.notManager')}</p>
              </Card>
            )}

            <Card as="section" aria-labelledby="people-leave">
              <CardTitle id="people-leave">{t('people.leaveSection')}</CardTitle>
              <p className={styles.text}>{t('people.leaveSectionText')}</p>
              <LeaveHomeButton homeId={homeId} homeName={data.name} onLeft={() => void left()} />
            </Card>

            {dialog === 'invite' && <InviteDialog homeId={homeId} owner={owner} onClose={() => setDialog(null)} />}
            {dialog === 'guest' && <GuestLinkDialog homeId={homeId} onClose={() => setDialog(null)} />}
            {dialog === 'device' && <DeviceDialog homeId={homeId} onClose={() => setDialog(null)} />}
          </div>
        )
      }}
    </QueryState>
  )
}
