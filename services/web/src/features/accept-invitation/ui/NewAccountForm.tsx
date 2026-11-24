import {type FormEvent, useState} from 'react'
import {useTranslation} from 'react-i18next'

import {useNewAccountFields, useStartSession} from '@/entities/account'
import {useAcceptWithNewAccount} from '@/entities/member'
import {describeError} from '@/shared/api'
import {Button, FormActions, FormError, FormLayout} from '@/shared/ui'

/** Makes an account through an invitation, the one way in besides the setup, and accepts the invitation. */
export function NewAccountForm(props: {token: string; onJoined: (homeId: string) => void}) {
  const {t, i18n} = useTranslation()
  const start = useStartSession()
  const accept = useAcceptWithNewAccount(props.token, start)
  const account = useNewAccountFields()
  const [problem, setProblem] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const read = account.read()
    setProblem(read.problem)
    if (!read.account) return
    accept.mutate({...read.account, locale: i18n.language}, {onSuccess: (answer) => props.onJoined(answer.home.id)})
  }

  const error = problem ?? (accept.isError ? describeError(accept.error, t) : null)
  return (
    <form onSubmit={submit}>
      <FormLayout>
        {account.fields}
        {error && <FormError>{error}</FormError>}
        <FormActions>
          <Button type="submit" disabled={accept.isPending}>
            {t('invitation.createAndJoin')}
          </Button>
        </FormActions>
      </FormLayout>
    </form>
  )
}
