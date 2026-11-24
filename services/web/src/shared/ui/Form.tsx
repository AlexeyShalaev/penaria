import {
  createContext,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  useContext,
  useId,
} from 'react'

import styles from './Form.module.css'

// The control inside a Field takes its id and hint from here, so the label names only the control.
const FieldContext = createContext<{id?: string; hintId?: string}>({})

/** A labelled control; `aside` sits next to the label, such as a mark that the field is locked. */
export function Field(props: {label: string; hint?: string; aside?: ReactNode; error?: string; children: ReactNode}) {
  const id = useId()
  const hintId = props.hint || props.error ? `${id}-hint` : undefined
  return (
    <div className={styles.field}>
      <span className={styles.labelRow}>
        <label className={styles.label} htmlFor={id}>
          {props.label}
        </label>
        {props.aside}
      </span>
      <FieldContext value={{id, hintId}}>{props.children}</FieldContext>
      {props.error ? (
        <span id={hintId} className={styles.fieldError}>
          {props.error}
        </span>
      ) : (
        props.hint && (
          <span id={hintId} className={styles.hint}>
            {props.hint}
          </span>
        )
      )}
    </div>
  )
}

export function TextInput({className, ...rest}: InputHTMLAttributes<HTMLInputElement>) {
  const field = useContext(FieldContext)
  return (
    <input
      id={field.id}
      aria-describedby={field.hintId}
      className={[styles.control, className].filter(Boolean).join(' ')}
      {...rest}
    />
  )
}

export function Select({className, ...rest}: SelectHTMLAttributes<HTMLSelectElement>) {
  const field = useContext(FieldContext)
  return (
    <select
      id={field.id}
      aria-describedby={field.hintId}
      className={[styles.control, className].filter(Boolean).join(' ')}
      {...rest}
    />
  )
}

/** The form's body: fields in a column, the buttons at the end. */
export function FormLayout(props: {children: ReactNode}) {
  return <div className={styles.layout}>{props.children}</div>
}

export function FormActions(props: {children: ReactNode}) {
  return <div className={styles.actions}>{props.children}</div>
}

export function FormError(props: {children: ReactNode}) {
  return (
    <p role="alert" className={styles.error}>
      {props.children}
    </p>
  )
}
