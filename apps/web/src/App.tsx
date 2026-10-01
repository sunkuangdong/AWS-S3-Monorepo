import './App.css'

import { useState } from 'react'

import type { AppPage } from './components/layout/AppHeader'
import { CreateImagePage } from './views/CreateImagePage'
import { ImageListPage } from './views/ImageListPage'

function App() {
  const [activePage, setActivePage] =
    useState<AppPage>('create')

  if (activePage === 'list') {
    return <ImageListPage onNavigate={setActivePage} />
  }

  return <CreateImagePage onNavigate={setActivePage} />
}

export default App
