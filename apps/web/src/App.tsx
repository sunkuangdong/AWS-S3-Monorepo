import './App.css'

import { useState } from 'react'
import { Tooltip } from 'radix-ui'

import type { AppPage } from './components/layout/AppHeader'
import { CreateImagePage } from './views/CreateImagePage'
import { ImageListPage } from './views/ImageListPage'

function App() {
  const [activePage, setActivePage] =
    useState<AppPage>('create')

  const activeView = activePage === 'list'
    ? <ImageListPage onNavigate={setActivePage} />
    : <CreateImagePage onNavigate={setActivePage} />

  return (
    <Tooltip.Provider
      delayDuration={250}
      skipDelayDuration={150}
    >
      {activeView}
    </Tooltip.Provider>
  )
}

export default App
