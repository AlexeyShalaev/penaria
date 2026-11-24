import {describe, expect, it} from 'vitest'

import type {Mailbox} from '@/entities/install'

import {draftOf, inputOf, isDirty, type MailboxDraft, validateMailbox, withSecurity} from './mailbox'

const DRAFT: MailboxDraft = {
  host: 'smtp.example.org',
  port: '587',
  security: 'starttls',
  username: 'home@example.org',
  password: '',
  from_address: 'home@example.org',
  from_name: 'Our home',
}

const OFF: Mailbox = {
  source: null,
  host: null,
  port: null,
  security: null,
  username: null,
  from_address: null,
  from_name: null,
  password_set: false,
}

describe('validateMailbox', () => {
  it('passes a complete form', () => {
    expect(validateMailbox(DRAFT, OFF)).toEqual({})
  })

  it('names every field that is wrong', () => {
    expect(validateMailbox({...DRAFT, host: ' ', port: '70000', from_address: 'home'}, OFF)).toEqual({
      host: 'hostRequired',
      port: 'portInvalid',
      from_address: 'fromInvalid',
    })
  })

  it.each(['0', '1.5', 'abc', ''])('refuses the port %j', (port) => {
    expect(validateMailbox({...DRAFT, port}, OFF).port).toBe('portInvalid')
  })
})

describe('withSecurity', () => {
  it('moves a default port to the security’s own', () => {
    expect(withSecurity(DRAFT, 'tls').port).toBe('465')
    expect(withSecurity({...DRAFT, port: '465'}, 'none').port).toBe('25')
  })

  it('keeps a port someone typed', () => {
    expect(withSecurity({...DRAFT, port: '2525'}, 'tls').port).toBe('2525')
  })
})

describe('inputOf', () => {
  it('trims the fields and leaves out an empty password and login', () => {
    expect(inputOf({...DRAFT, host: ' smtp.example.org ', username: ' ', from_name: ''})).toEqual({
      host: 'smtp.example.org',
      port: 587,
      security: 'starttls',
      username: null,
      password: null,
      from_address: 'home@example.org',
      from_name: null,
    })
  })
})

describe('draftOf and isDirty', () => {
  it('starts an empty form at STARTTLS on port 587 when mail is off', () => {
    expect(draftOf(OFF)).toEqual({...DRAFT, host: '', username: '', from_address: '', from_name: ''})
  })

  it('sees a typed password or a changed field as unsaved', () => {
    const saved: Mailbox = {...OFF, source: 'interface', ...DRAFT, port: 587, password_set: true}

    expect(isDirty(draftOf(saved), saved)).toBe(false)
    expect(isDirty({...draftOf(saved), password: 'new'}, saved)).toBe(true)
    expect(isDirty({...draftOf(saved), from_name: 'Home'}, saved)).toBe(true)
  })
})

describe('the saved password', () => {
  const saved: Mailbox = {...OFF, source: 'interface', ...DRAFT, port: 587, password_set: true}

  it('stays with the server and login it was given for', () => {
    expect(validateMailbox({...draftOf(saved), from_name: 'Dacha'}, saved)).toEqual({})
  })

  it.each([
    ['host', {host: 'smtp.elsewhere.org'}],
    ['port', {port: '25'}],
    ['security', {security: 'none' as const}],
    ['login', {username: 'someone@example.org'}],
  ])('is asked for again when the %s changes', (_, changes) => {
    expect(validateMailbox({...draftOf(saved), ...changes}, saved)).toEqual({password: 'passwordAgain'})
    expect(validateMailbox({...draftOf(saved), ...changes, password: 'typed'}, saved)).toEqual({})
  })
})
