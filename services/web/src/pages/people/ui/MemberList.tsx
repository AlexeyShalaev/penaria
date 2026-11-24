import {Clock} from 'lucide-react'
import {useState} from 'react'
import {useTranslation} from 'react-i18next'

import {ChangeAccessDialog} from '@/features/give-access'
import {ResetLinkDialog} from '@/features/reset-link'
import {useRecentSignIn} from '@/entities/account'
import {
  type Member,
  type MemberGrant,
  RoleBadge,
  roleName,
  scopeLabel,
  useMembers,
  useRevokeGrant,
} from '@/entities/member'
import {describeError} from '@/shared/api'
import {formatDateTime} from '@/shared/lib/time'
import {Badge, Button, Dialog, FormActions, FormError, FormLayout, QueryState} from '@/shared/ui'

import styles from './Lists.module.css'

type Target = {member: Member; grant: MemberGrant}

/** The home's members with each of their grants; a grant can be changed or taken back. */
export function MemberList(props: {homeId: string; owner: boolean}) {
  const {t} = useTranslation()
  const members = useMembers(props.homeId)
  const [changing, setChanging] = useState<Target | null>(null)
  const [removing, setRemoving] = useState<Target | null>(null)
  const [resetting, setResetting] = useState<Member | null>(null)

  return (
    <QueryState query={members}>
      {(list) => (
        <>
          <ul className={styles.list}>
            {list.map((member) => (
              <li key={member.person.id} className={styles.row}>
                <span className={styles.avatar} aria-hidden>
                  {initial(member.person.display_name)}
                </span>
                <div className={styles.body}>
                  <span className={styles.title}>
                    {member.person.display_name}
                    {member.person.username && <span className={styles.username}>@{member.person.username}</span>}
                    {member.you && <Badge tone="ok">{t('people.you')}</Badge>}
                    {!member.you && (
                      <Button variant="ghost" size="sm" className={styles.reset} onClick={() => setResetting(member)}>
                        {t('resetLink.action')}
                      </Button>
                    )}
                  </span>
                  {member.grants.map((grant) => (
                    <GrantLine
                      key={grant.id}
                      grant={grant}
                      canChange={!member.you && grant.role.preset !== 'owner'}
                      canRemove={!member.you && (grant.role.preset !== 'owner' || props.owner)}
                      onChange={() => setChanging({member, grant})}
                      onRemove={() => setRemoving({member, grant})}
                    />
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {changing && (
            <ChangeAccessDialog
              homeId={props.homeId}
              person={changing.member.person.display_name}
              grant={changing.grant}
              onClose={() => setChanging(null)}
            />
          )}
          {removing && <RemoveDialog homeId={props.homeId} target={removing} onClose={() => setRemoving(null)} />}
          {resetting && (
            <ResetLinkDialog
              homeId={props.homeId}
              userId={resetting.person.id}
              name={resetting.person.display_name}
              onClose={() => setResetting(null)}
            />
          )}
        </>
      )}
    </QueryState>
  )
}

function GrantLine(props: {
  grant: MemberGrant
  canChange: boolean
  canRemove: boolean
  onChange: () => void
  onRemove: () => void
}) {
  const {t, i18n} = useTranslation()
  const {grant} = props
  const details = [
    scopeLabel(grant.scope, t),
    grant.granted_by && t('people.invitedBy', {name: grant.granted_by.display_name}),
  ].filter(Boolean)
  return (
    <div className={styles.grant}>
      <RoleBadge role={grant.role} />
      <span className={styles.details}>{details.join(' · ')}</span>
      {grant.expires_at && (
        <Badge icon={Clock}>
          {t('people.until', {when: formatDateTime(new Date(grant.expires_at), i18n.language)})}
        </Badge>
      )}
      <span className={styles.grantActions}>
        {props.canChange && (
          <Button variant="ghost" size="sm" onClick={props.onChange}>
            {t('people.change')}
          </Button>
        )}
        {props.canRemove && (
          <Button variant="ghost" size="sm" onClick={props.onRemove}>
            {t('people.remove')}
          </Button>
        )}
      </span>
    </div>
  )
}

function RemoveDialog(props: {homeId: string; target: Target; onClose: () => void}) {
  const {t} = useTranslation()
  const revoke = useRevokeGrant(props.homeId)
  const recent = useRecentSignIn()
  const {member, grant} = props.target
  const confirm = () => {
    const send = () => revoke.mutate(grant.id, {onSuccess: props.onClose, onError: recent.retryOnError(send)})
    send()
  }
  const error = recent.errorToShow(revoke.error)
  return (
    <>
      <Dialog
        title={t('people.removeTitle', {name: member.person.display_name})}
        closeLabel={t('common.close')}
        onClose={props.onClose}
      >
        <FormLayout>
          <p className={styles.text}>
            {t('people.removeText', {name: member.person.display_name, role: roleName(grant.role, t)})}
          </p>
          {error && <FormError>{describeError(error, t)}</FormError>}
          <FormActions>
            <Button variant="secondary" onClick={props.onClose}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" disabled={revoke.isPending} onClick={confirm}>
              {t('people.remove')}
            </Button>
          </FormActions>
        </FormLayout>
      </Dialog>
      {recent.dialog}
    </>
  )
}

function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase()
}
