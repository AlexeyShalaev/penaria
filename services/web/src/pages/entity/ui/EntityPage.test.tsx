import {fireEvent, screen, within} from '@testing-library/react'
import {Route} from 'react-router'
import {describe, expect, it} from 'vitest'

import {type ApiCall, mockApi, problem} from '@/test/api'
import {detail, entity, HOME_ID} from '@/test/fixtures'
import {renderAt} from '@/test/render'

import {EntityPage} from './EntityPage'

const VACUUM = detail({
  id: 'vacuum',
  name: 'Vacuum cleaner',
  kind: 'item',
  parent_id: 'storage',
  version: 3,
  freshness: 'doubtful',
  path: [
    {id: 'flat', name: 'Flat', kind: 'property'},
    {id: 'storage', name: 'Storage room', kind: 'space'},
  ],
})
const ENTITIES = `GET /api/v1/homes/${HOME_ID}/entities`
const PAGE = {
  'GET /api/v1/entities/vacuum': VACUUM,
  [`${ENTITIES}?parent_id=vacuum`]: [],
}

/** The page's answers, where a write also changes what the entity reads as afterwards. */
function pageWith(write: string, after: typeof VACUUM) {
  let current = VACUUM
  return {
    ...PAGE,
    'GET /api/v1/entities/vacuum': () => current,
    [write]: () => {
      current = after
      return after
    },
  }
}

function renderEntity() {
  return renderAt('/entities/vacuum', <Route path="/entities/:entityId" element={<EntityPage />} />)
}

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method !== 'GET')

describe('EntityPage', () => {
  it('shows where the entity is and how fresh that is', async () => {
    mockApi(PAGE)

    renderEntity()

    expect(await screen.findByRole('heading', {name: 'Vacuum cleaner'})).toBeVisible()
    const crumbs = screen.getByRole('navigation', {name: 'Where it is'})
    expect(
      within(crumbs)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Places and things', 'Flat', 'Storage room'])
    expect(within(screen.getByRole('banner')).getByText('Never checked')).toBeVisible()
    expect(screen.getByText('Flat → Storage room')).toBeVisible()
  })

  it('confirms the entity is here', async () => {
    const calls = mockApi(
      pageWith('POST /api/v1/entities/vacuum:verify', {
        ...VACUUM,
        verified_at: new Date().toISOString(),
        freshness: 'fresh',
      }),
    )
    renderEntity()

    fireEvent.click(await screen.findByRole('button', {name: "It's here"}))

    expect(await screen.findByText('Checked now')).toBeVisible()
    expect(writes(calls)).toEqual([
      {method: 'POST', path: '/api/v1/entities/vacuum:verify', search: '', body: undefined},
    ])
  })

  it('moves the entity to a place it fits in', async () => {
    const calls = mockApi({
      ...pageWith('POST /api/v1/entities/vacuum:move', {...VACUUM, parent_id: 'kitchen', version: 4}),
      [ENTITIES]: [entity({id: 'flat', name: 'Flat', kind: 'property', children: 2})],
      [`${ENTITIES}?parent_id=flat`]: [
        entity({id: 'storage', name: 'Storage room', kind: 'space', parent_id: 'flat', children: 1}),
        entity({id: 'kitchen', name: 'Kitchen', kind: 'space', parent_id: 'flat'}),
      ],
      [`${ENTITIES}?parent_id=storage`]: [entity({id: 'vacuum', name: 'Vacuum cleaner', kind: 'item'})],
    })
    renderEntity()

    fireEvent.click(await screen.findByRole('button', {name: 'Move'}))
    const dialog = await screen.findByRole('dialog', {name: 'Move Vacuum cleaner'})
    expect(await within(dialog).findByRole('button', {name: /^Flat/})).toBeDisabled()
    expect(await within(dialog).findByRole('button', {name: /^Storage room/})).toBeDisabled()
    expect(within(dialog).queryByText('Vacuum cleaner')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', {name: /^Kitchen/}))
    fireEvent.click(within(dialog).getByRole('button', {name: 'Move here'}))

    await screen.findByRole('button', {name: 'Move'})
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(writes(calls)).toEqual([
      {method: 'POST', path: '/api/v1/entities/vacuum:move', search: '', body: {parent_id: 'kitchen', version: 3}},
    ])
  })

  it('saves only what was edited, with the version it is based on', async () => {
    const calls = mockApi(
      pageWith('PATCH /api/v1/entities/vacuum', {...VACUUM, name: 'Cordless vacuum', status: 'lent', version: 4}),
    )
    renderEntity()

    fireEvent.click(await screen.findByRole('button', {name: 'Edit'}))
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Cordless vacuum'}})
    fireEvent.change(screen.getByLabelText('Status'), {target: {value: 'lent'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByRole('heading', {name: 'Cordless vacuum'})).toBeVisible()
    expect(writes(calls)).toEqual([
      {
        method: 'PATCH',
        path: '/api/v1/entities/vacuum',
        search: '',
        body: {version: 3, name: 'Cordless vacuum', status: 'lent'},
      },
    ])
  })

  it('reloads and says so when someone else changed the entity first', async () => {
    let reads = 0
    mockApi({
      ...PAGE,
      'GET /api/v1/entities/vacuum': () => (reads++ === 0 ? VACUUM : {...VACUUM, name: 'Robot vacuum', version: 4}),
      'PATCH /api/v1/entities/vacuum': problem(409, 'stale_version'),
    })
    renderEntity()

    fireEvent.click(await screen.findByRole('button', {name: 'Edit'}))
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Cordless vacuum'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save'}))

    expect(await screen.findByRole('alert')).toHaveTextContent('Someone changed this in the meantime.')
    expect(await screen.findByLabelText('Name')).toHaveValue('Robot vacuum')
  })

  it('archives the entity for the reason given', async () => {
    const calls = mockApi(
      pageWith('POST /api/v1/entities/vacuum:archive', {
        ...VACUUM,
        archived_at: new Date().toISOString(),
        archive_reason: 'sold',
        version: 4,
      }),
    )
    renderEntity()

    fireEvent.click(await screen.findByRole('button', {name: 'Archive'}))
    fireEvent.click(screen.getByRole('radio', {name: 'Sold'}))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', {name: 'Archive'}))

    expect(await screen.findByRole('button', {name: 'Restore'})).toBeVisible()
    expect(writes(calls)).toEqual([
      {method: 'POST', path: '/api/v1/entities/vacuum:archive', search: '', body: {reason: 'sold', version: 3}},
    ])
  })

  it('offers no changes to someone who may only look', async () => {
    mockApi({...PAGE, 'GET /api/v1/entities/vacuum': {...VACUUM, can_edit: false}})

    renderEntity()

    expect(await screen.findByText('You can see this, but not change it.')).toBeVisible()
    expect(screen.queryByRole('button', {name: "It's here"})).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: 'Edit'})).not.toBeInTheDocument()
  })

  it('tells the history in sentences', async () => {
    mockApi({
      ...PAGE,
      'GET /api/v1/entities/vacuum/history': [
        {
          id: 'e2',
          type: 'entity.moved',
          at: '2026-11-20T10:00:00Z',
          actor: {kind: 'user', id: 'u1'},
          payload: {name: 'Vacuum cleaner', from: {name: 'Storage room'}, to: {name: 'Kitchen'}},
        },
        {
          id: 'e1',
          type: 'entity.created',
          at: '2026-11-19T10:00:00Z',
          actor: {kind: 'user', id: 'u1'},
          payload: {kind: 'item', name: 'Vacuum cleaner', parent: {name: 'Storage room'}},
        },
      ],
    })
    renderEntity()

    fireEvent.click(await screen.findByRole('tab', {name: 'History'}))

    expect(await screen.findByText('Moved from Storage room to Kitchen')).toBeVisible()
    expect(screen.getByText('Added to Storage room')).toBeVisible()
  })

  it('says when the entity is not there', async () => {
    mockApi({'GET /api/v1/entities/vacuum': problem(404, 'entity_not_found')})

    renderEntity()

    expect(await screen.findByText('Not found')).toBeVisible()
  })
})
