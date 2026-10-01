export type AppPage = 'list' | 'create'

interface AppHeaderProps {
  activePage: AppPage
  onNavigate: (page: AppPage) => void
}

function SparkleIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 2.8c.6 4.8 3.1 7.3 7.9 7.9-4.8.6-7.3 3.1-7.9 7.9-.6-4.8-3.1-7.3-7.9-7.9C8.9 10.1 11.4 7.6 12 2.8Z" />
      <path d="M19 16.8c.2 1.6 1.1 2.5 2.7 2.7-1.6.2-2.5 1.1-2.7 2.7-.2-1.6-1.1-2.5-2.7-2.7 1.6-.2 2.5-1.1 2.7-2.7Z" />
    </svg>
  )
}

/**
 * 应用共享页头及一级页面导航。
 * Shared app header and primary page navigation.
 */
export function AppHeader({
  activePage,
  onNavigate,
}: AppHeaderProps) {
  return (
    <header className="app-header">
      <button
        className="brand"
        type="button"
        onClick={() => onNavigate('list')}
        aria-label="打开 AI 画板创作列表"
      >
        <span className="brand-mark">
          <SparkleIcon />
        </span>
        <span>AI 画板</span>
      </button>

      <nav className="app-navigation" aria-label="主要页面">
        <button
          className={activePage === 'list' ? 'is-active' : ''}
          type="button"
          onClick={() => onNavigate('list')}
          aria-current={activePage === 'list' ? 'page' : undefined}
        >
          列表
        </button>
        <button
          className={activePage === 'create' ? 'is-active' : ''}
          type="button"
          onClick={() => onNavigate('create')}
          aria-current={activePage === 'create' ? 'page' : undefined}
        >
          创作
        </button>
      </nav>
    </header>
  )
}
