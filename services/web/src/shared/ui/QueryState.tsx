import type {UseQueryResult} from '@tanstack/react-query'
import type {ReactNode} from 'react'
import {useTranslation} from 'react-i18next'

import {describeError} from '@/shared/api'

import {ErrorState, Loading} from './State'

type Props<T> = {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
  /** Puts the spinner or the error where the data would go, such as into a list item. */
  wrap?: (state: ReactNode) => ReactNode
}

/** The data of a query once it is there; until then a spinner, or the error with a retry. */
export function QueryState<T>({query, children, wrap = (state) => state}: Props<T>) {
  const {t} = useTranslation()
  if (query.isPending) return wrap(<Loading label={t('common.loading')} />)
  if (query.isError) {
    return wrap(
      <ErrorState
        message={describeError(query.error, t)}
        retryLabel={t('common.retry')}
        onRetry={() => void query.refetch()}
      />,
    )
  }
  return children(query.data)
}
