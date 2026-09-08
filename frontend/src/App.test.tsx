import { render, screen } from '@testing-library/react'

import App from './App'

describe('App', () => {
  it('renders the Chinese workbench title', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: '可信知识库工作台' })).toBeInTheDocument()
  })
})
