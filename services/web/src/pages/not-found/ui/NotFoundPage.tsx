import {SearchX} from 'lucide-react'
import {useTranslation} from 'react-i18next'
import {Link} from 'react-router'

import {Empty} from '@/shared/ui'

export function NotFoundPage() {
  const {t} = useTranslation()
  return (
    <Empty
      icon={SearchX}
      title={t('notFound.title')}
      text={t('notFound.text')}
      action={<Link to="/">{t('notFound.home')}</Link>}
    />
  )
}
