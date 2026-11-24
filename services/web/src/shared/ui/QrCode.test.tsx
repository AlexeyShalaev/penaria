import {render, screen} from '@testing-library/react'
import {describe, expect, it} from 'vitest'

import {QrCode} from './QrCode'

describe('QrCode', () => {
  it('draws the link as a square of dark modules', () => {
    render(<QrCode value="https://home.example.org/guest/abc" label="QR code" />)

    const svg = screen.getByRole('img', {name: 'QR code'})
    const [width, height] = (svg.getAttribute('viewBox') ?? '').split(' ').slice(2).map(Number)

    expect(width).toBe(height)
    // Version 3 at medium correction holds this link: 29 modules and a border of 2 on each side.
    expect(width).toBe(33)
    expect(svg.querySelector('path')?.getAttribute('d')).toMatch(/^M2 2h1v1h-1z/)
  })
})
