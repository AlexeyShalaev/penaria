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

const ENTITIES = `GET /api/v1/homes/${HOME_ID}/entities`

function renderPlaces() {
  return renderAt(`/homes/${HOME_ID}/places`, <Route path="/homes/:homeId/places" element={<PlacesPage />} />)
}

describe('PlacesPage', () => {
  it('opens the properties and loads the contents of a place when it is expanded', async () => {
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [ENTITIES]: [FLAT],
      [`${ENTITIES}?parent_id=flat`]: [KITCHEN, STORAGE],
      [`${ENTITIES}?parent_id=kitchen`]: [DRAWER],
    })

    renderPlaces()

    const kitchen = await screen.findByRole('link', {name: /Kitchen/})
    expect(kitchen).toHaveTextContent('Room or area · 1 inside')
    expect(kitchen).toHaveAttribute('href', '/entities/kitchen')
    expect(within(screen.getByRole('link', {name: /Storage room/})).getByRole('img', {name: 'Private'})).toBeVisible()
    expect(screen.queryByText('Drawer')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', {name: 'Show what is inside Kitchen'}))

    expect(await screen.findByRole('link', {name: /Drawer/})).toHaveTextContent('Storage')
    expect(screen.getByRole('button', {name: 'Hide what is inside Kitchen'})).toHaveAttribute('aria-expanded', 'true')
    expect(calls.map((call) => `${call.path}${call.search}`)).toContain(
      `/api/v1/homes/${HOME_ID}/entities?parent_id=kitchen`,
    )
  })

  it('invites to add the property when the home is empty', async () => {
    mockApi({[`GET /api/v1/homes/${HOME_ID}`]: home(), [ENTITIES]: []})

    renderPlaces()

    expect(await screen.findByText('Nothing here yet')).toBeVisible()
    expect(screen.getByRole('button', {name: 'Add a property'})).toBeVisible()
  })

  it('asks for archived places too when they are shown', async () => {
    const calls = mockApi({
      [`GET /api/v1/homes/${HOME_ID}`]: home(),
      [ENTITIES]: [FLAT],
      [`${ENTITIES}?parent_id=flat`]: [],
    })

    renderPlaces()
    await screen.findByRole('link', {name: /Flat/})
    fireEvent.click(screen.getByRole('button', {name: 'Show archived'}))

    await screen.findByRole('link', {name: /Flat/})
    expect(calls.map((call) => call.search)).toContain('?include_archived=true')
  })
})
