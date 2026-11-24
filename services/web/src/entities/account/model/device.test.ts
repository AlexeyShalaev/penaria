import {describe, expect, it} from 'vitest'

import {describeDevice} from './device'

describe('describeDevice', () => {
  it.each([
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0',
      {browser: 'Edge', system: 'Windows'},
    ],
    [
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
      {browser: 'Safari', system: 'iPhone'},
    ],
    ['Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0', {browser: 'Firefox', system: 'Linux'}],
    ['curl/8.7.1', {browser: null, system: null}],
    [null, {browser: null, system: null}],
  ])('tells the browser and system of %s', (userAgent, expected) => {
    expect(describeDevice(userAgent)).toEqual(expected)
  })
})
