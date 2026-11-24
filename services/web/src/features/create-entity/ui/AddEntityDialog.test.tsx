import {fireEvent, screen} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it, vi} from 'vitest'

import {mockApi} from '@/test/api'
import {detail, entity, HOME_ID} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import type {Place} from '@/entities/entity'

import {AddEntityDialog} from './AddEntityDialog'

function renderDialog(parent: Place | null, canChangePlace = false) {
  const onCreated = vi.fn()
  renderAt(
    '/',
    <Route
      path="/"
      element={
        <AddEntityDialog
          homeId={HOME_ID}
          parent={parent}
          canChangePlace={canChangePlace}
          onClose={() => {}}
          onCreated={onCreated}
        />
      }
    />,
  )
  return onCreated
}

const kindNames = () => screen.getAllByRole('radio').map((radio) => radio.textContent)

describe('AddEntityDialog', () => {
  it('offers only a property at the top of the home', () => {
    renderDialog(null)

    expect(kindNames()).toEqual(['Property'])
  })

  it('offers what fits inside a room', () => {
    renderDialog({id: 'kitchen', kind: 'space', name: 'Kitchen'})

    expect(kindNames()).toEqual(['Room or area', 'Storage', 'Thing', 'Device'])
  })

  it('offers the kinds of the place picked instead', async () => {
    mockApi({[`GET /api/v1/homes/${HOME_ID}/entities`]: [entity({id: 'flat', name: 'Flat', kind: 'property'})]})
    renderDialog(null, true)

    fireEvent.click(screen.getByRole('button', {name: 'Change'}))
    fireEvent.click(await screen.findByRole('button', {name: /Flat/}))

    expect(kindNames()).toEqual(['Building', 'Room or area', 'System'])
  })

  it('creates the entity inside the parent', async () => {
    const created = detail({id: 'drill', name: 'Drill', kind: 'item', parent_id: 'storage'})
    const calls = mockApi({[`POST /api/v1/homes/${HOME_ID}/entities`]: created})
    const onCreated = renderDialog({id: 'storage', kind: 'space', name: 'Storage room'})

    fireEvent.click(screen.getByRole('radio', {name: 'Thing'}))
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: ' Drill '}})
    fireEvent.change(screen.getByLabelText(/Other names/), {target: {value: 'hammer drill, '}})
    fireEvent.change(screen.getByLabelText('Quantity'), {target: {value: '2'}})
    fireEvent.change(screen.getByLabelText('Who can see it'), {target: {value: 'private'}})
    fireEvent.click(screen.getByRole('button', {name: 'Add'}))

    await vi.waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(calls).toEqual([
      {
        method: 'POST',
        path: `/api/v1/homes/${HOME_ID}/entities`,
        search: '',
        body: {
          kind: 'item',
          parent_id: 'storage',
          name: 'Drill',
          aliases: ['hammer drill'],
          quantity: '2',
          unit: null,
          privacy: 'private',
        },
      },
    ])
  })

  it('leaves out the quantity when the kind chosen is not a thing', async () => {
    const created = detail({id: 'shelf', name: 'Shelf', kind: 'container', parent_id: 'storage'})
    const calls = mockApi({[`POST /api/v1/homes/${HOME_ID}/entities`]: created})
    const onCreated = renderDialog({id: 'storage', kind: 'space', name: 'Storage room'})

    fireEvent.click(screen.getByRole('radio', {name: 'Thing'}))
    fireEvent.change(screen.getByLabelText('Quantity'), {target: {value: '2'}})
    fireEvent.change(screen.getByLabelText('Unit'), {target: {value: 'kg'}})
    fireEvent.click(screen.getByRole('radio', {name: 'Storage'}))
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Shelf'}})
    fireEvent.click(screen.getByRole('button', {name: 'Add'}))

    await vi.waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(screen.queryByLabelText('Quantity')).not.toBeInTheDocument()
    expect(calls[0]?.body).toMatchObject({kind: 'container', quantity: null, unit: null})
  })
})
