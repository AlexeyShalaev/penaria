import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {mockApi} from '@/test/api'
import {entity, home, HOME_ID} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {PlacesPage} from './PlacesPage'

const FLAT = entity({id: 'flat', name: 'Flat', kind: 'property', children: 2})
const KITCHEN = entity({id: 'kitchen', name: 'Kitchen', kind: 'space', parent_id: 'flat', children: 1})
const STORAGE = entity({id: 'storage', name: 'Storage room', kind: 'space', parent_id: 'flat', privacy: 'private'})
const DRAWER = entity({id: 'drawer', name: 'Drawer', kind: 'container', parent_id: 'kitchen'})

const HOME = `GET /api/v1/homes/${HOME_ID}`
const ENTITIES = `GET /api/v1/homes/${HOME_ID}/entities`
const TREE = {
  [HOME]: home(),
  [ENTITIES]: [FLAT],
  [`${ENTITIES}?parent_id=flat`]: [KITCHEN, STORAGE],
  [`${ENTITIES}?parent_id=kitchen`]: [DRAWER],
}

function renderPlaces() {
  return renderAt(`/homes/${HOME_ID}/places`, <Route path="/homes/:homeId/places" element={<PlacesPage />} />)
}

const asked = (calls: {path: string; search: string}[]) => calls.map((call) => `${call.path}${call.search}`)

describe('PlacesPage', () => {
  it('opens the properties and loads the contents of a place when it is expanded', async () => {
    const calls = mockApi(TREE)

    renderPlaces()

    const kitchen = await screen.findByRole('link', {name: /Kitchen/})
    expect(kitchen).toHaveTextContent('Room or area · 1 inside')
    expect(kitchen).toHaveAttribute('href', '/entities/kitchen')
    expect(within(screen.getByRole('link', {name: /Storage room/})).getByRole('img', {name: 'Private'})).toBeVisible()
    expect(screen.queryByText('Drawer')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', {name: 'Show what is inside Kitchen'}))

    expect(await screen.findByRole('link', {name: /Drawer/})).toHaveTextContent('Storage')
    expect(screen.getByRole('button', {name: 'Hide what is inside Kitchen'})).toHaveAttribute('aria-expanded', 'true')
    expect(asked(calls)).toEqual([
      `/api/v1/homes/${HOME_ID}`,
      `/api/v1/homes/${HOME_ID}/entities`,
      `/api/v1/homes/${HOME_ID}/entities?parent_id=flat`,
      `/api/v1/homes/${HOME_ID}/entities?parent_id=kitchen`,
    ])
  })

  it('keeps the places that were open when the page is left and opened again', async () => {
    mockApi(TREE)
    const first = renderPlaces()
    fireEvent.click(await screen.findByRole('button', {name: 'Show what is inside Kitchen'}))
    await screen.findByRole('link', {name: /Drawer/})
    first.unmount()

    renderPlaces()

    expect(await screen.findByRole('link', {name: /Drawer/})).toBeVisible()
  })

  it('names the kind and the count in Russian', async () => {
    mockApi({...TREE, [`${ENTITIES}?parent_id=flat`]: [{...KITCHEN, children: 3}]})
    const {i18n} = await import('@/shared/i18n')
    await i18n.changeLanguage('ru')

    renderPlaces()

    expect(await screen.findByRole('link', {name: /Kitchen/})).toHaveTextContent('Помещение · внутри: 3')
  })

  it('invites to add the property when the home is empty', async () => {
    mockApi({[HOME]: home(), [ENTITIES]: []})

    renderPlaces()

    expect(await screen.findByText('Nothing here yet')).toBeVisible()
    expect(screen.getByRole('button', {name: 'Add a property'})).toBeVisible()
  })

  it('offers no adding to someone who may only look', async () => {
    mockApi({
      [HOME]: home({access: {owner: false, all_permissions: false, permissions: ['entities.view']}}),
      [ENTITIES]: [],
    })

    renderPlaces()

    expect(await screen.findByText('Nothing here yet')).toBeVisible()
    expect(screen.queryByRole('button', {name: 'Add'})).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: 'Add a property'})).not.toBeInTheDocument()
  })

  it('offers adding to a member who may edit', async () => {
    mockApi({
      [HOME]: home({access: {owner: false, all_permissions: false, permissions: ['entities.edit']}}),
      [ENTITIES]: [],
    })

    renderPlaces()

    expect(await screen.findByRole('button', {name: 'Add'})).toBeVisible()
  })

  it('shows archived entities, also inside places whose count leaves them out', async () => {
    const kettle = entity({id: 'kettle', name: 'Old kettle', kind: 'item', archived_at: '2026-11-01T10:00:00Z'})
    mockApi({
      ...TREE,
      [`${ENTITIES}?include_archived=true`]: [FLAT],
      [`${ENTITIES}?parent_id=flat&include_archived=true`]: [{...KITCHEN, children: 0}, STORAGE],
      [`${ENTITIES}?parent_id=kitchen&include_archived=true`]: [],
      [`${ENTITIES}?parent_id=storage&include_archived=true`]: [kettle],
    })
    renderPlaces()
    await screen.findByRole('link', {name: /Kitchen/})

    fireEvent.click(screen.getByRole('button', {name: 'Show archived'}))
    fireEvent.click(await screen.findByRole('button', {name: 'Show what is inside Storage room'}))

    expect(await screen.findByRole('link', {name: /Old kettle/})).toHaveTextContent('Archived')
    fireEvent.click(screen.getByRole('button', {name: 'Show what is inside Kitchen'}))
    expect(await screen.findByText('Nothing inside yet.')).toBeVisible()
  })
})
