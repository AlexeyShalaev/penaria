import {useTranslation} from 'react-i18next'

import type {Role} from '../api/people'
import {roleDescription, roleName} from '../model/roles'
import styles from './RolePicker.module.css'

/** The roles to choose from, each with what it lets its holder do. */
export function RolePicker(props: {
  label: string
  roles: Role[]
  value: string | null
  onChange: (role: Role) => void
}) {
  const {t} = useTranslation()
  return (
    <fieldset className={styles.picker}>
      <legend className={styles.legend}>{props.label}</legend>
      {props.roles.map((role) => {
        const description = roleDescription(role, t)
        return (
          <label key={role.id} className={styles.option}>
            <input
              type="radio"
              name="role"
              value={role.id}
              checked={props.value === role.id}
              onChange={() => props.onChange(role)}
            />
            <span className={styles.text}>
              <span className={styles.name}>{roleName(role, t)}</span>
              {description && <span className={styles.description}>{description}</span>}
            </span>
          </label>
        )
      })}
    </fieldset>
  )
}
