import {describe, expect, it} from 'vitest'

import type {EntityEvent} from '@/entities/entity'
import {i18n} from '@/shared/i18n'

import {describeEvent} from './history'

const event = (type: string, payload: Record<string, unknown>): EntityEvent => ({
  id: 'e1',
  type,
  at: '2026-11-20T10:00:00Z',
  actor: {kind: 'user', id: 'u1'},
  payload,
})

const STORAGE = {id: 's', name: 'Storage room', kind: 'space'}
const KITCHEN = {id: 'k', name: 'Kitchen', kind: 'space'}

describe('describeEvent', () => {
  it.each([
    ['entity.created', {kind: 'item', name: 'Drill', parent: STORAGE}, ['Added to Storage room']],
    ['entity.created', {kind: 'property', name: 'Flat', parent: null}, ['Added']],
    ['entity.moved', {name: 'Drill', from: STORAGE, to: KITCHEN}, ['Moved from Storage room to Kitchen']],
    ['entity.moved', {name: 'Drill', from: null, to: KITCHEN}, ['Moved to Kitchen']],
    ['entity.moved', {name: 'Drill', from: KITCHEN, to: null}, ['Moved']],
    ['entity.archived', {name: 'Drill', reason: 'sold'}, ['Archived: Sold']],
    ['entity.restored', {name: 'Drill'}, ['Restored from the archive']],
    ['entity.verified', {name: 'Drill'}, ['Confirmed it is in place']],
    ['entity.updated', {name: {from: 'Drill', to: 'Hammer drill'}}, ['Renamed from “Drill” to “Hammer drill”']],
    ['entity.updated', {aliases: {from: [], to: ['drill', 'driver']}}, ['Other names set to drill, driver']],
    ['entity.updated', {aliases: {from: ['drill'], to: []}}, ['Other names removed']],
    [
      'entity.updated',
      {quantity: {from: null, to: '2'}, unit: {from: null, to: 'kg'}},
      ['Quantity set to 2', 'Unit set to kg'],
    ],
    [
      'entity.updated',
      {quantity: {from: '2', to: null}, unit: {from: 'kg', to: null}},
      ['Quantity removed', 'Unit removed'],
    ],
    [
      'entity.updated',
      {status: {from: 'present', to: 'lent'}, privacy: {from: 'normal', to: 'private'}},
      ['Status changed from In place to Lent out', 'Visibility changed from Everyone in the home to Private'],
    ],
    ['entity.updated', {colour: {from: 'red', to: 'blue'}}, ['Changed']],
    ['entity.updated', {aliases: {from: [], to: 'not a list'}}, ['Changed']],
    ['knx.bus.offline', {}, ['Changed']],
  ])('%s %j reads as %j', (type, payload, expected) => {
    expect(describeEvent(event(type, payload), i18n.t)).toEqual(expected)
  })
})
