import createClient from 'openapi-fetch'

import type {components, paths} from './schema.gen'

export type Schemas = components['schemas']

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Looked up on every call, so tests can replace the global fetch.
  fetch: (request) => fetch(request),
})
