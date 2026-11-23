import {StrictMode} from 'react'
import {createRoot} from 'react-dom/client'

import {App} from '@/app/App'
import {detectLanguage, initI18n} from '@/shared/i18n'
import '@/shared/ui/tokens.css'
import '@/shared/ui/base.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root is missing from index.html')

const language = detectLanguage(navigator.languages)
document.documentElement.lang = language
if (window.matchMedia('(prefers-color-scheme: dark)').matches) document.documentElement.dataset.theme = 'dark'

await initI18n(language)

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
