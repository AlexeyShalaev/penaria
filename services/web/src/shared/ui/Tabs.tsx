import styles from './Tabs.module.css'

type Props<T extends string> = {
  label: string
  value: T
  options: {value: T; label: string}[]
  onChange: (value: T) => void
}

export function Tabs<T extends string>({label, value, options, onChange}: Props<T>) {
  return (
    <div className={styles.tabs} role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
