import i18n from 'i18next'
import {initReactI18next} from 'react-i18next'

import en from './locales/en.json'
import ru from './locales/ru.json'

export const SUPPORTED_LANGUAGES = ['en', 'ru'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

export const resources = {en: {translation: en}, ru: {translation: ru}} as const

/** The browser's first supported language, English otherwise. */
export function detectLanguage(preferred: readonly string[]): Language {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split('-')[0]
    const match = SUPPORTED_LANGUAGES.find((language) => language === base)
    if (match) return match
  }
  return 'en'
}

export function initI18n(language: Language) {
  return i18n.use(initReactI18next).init({
    resources,
    lng: language,
    fallbackLng: 'en',
    interpolation: {escapeValue: false},
  })
}

export {i18n}
