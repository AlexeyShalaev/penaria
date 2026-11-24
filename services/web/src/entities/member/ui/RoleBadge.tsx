import {useTranslation} from 'react-i18next'

import {Badge} from '@/shared/ui'

import type {Role} from '../api/people'
import {ROLE_TONE, roleName} from '../model/roles'

export function RoleBadge(props: {role: Pick<Role, 'preset' | 'name'>}) {
  const {t} = useTranslation()
  return <Badge tone={props.role.preset ? ROLE_TONE[props.role.preset] : 'neutral'}>{roleName(props.role, t)}</Badge>
}
