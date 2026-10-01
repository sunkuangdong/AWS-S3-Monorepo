import {
  AppHeader,
} from '../components/layout/AppHeader'
import type { AppPage } from '../components/layout/AppHeader'
import { ImageGenerationCard } from '../components/image-list/ImageGenerationCard'
import { ImageListEmpty } from '../components/image-list/ImageListEmpty'
import { ImageListPagination } from '../components/image-list/ImageListPagination'
import { ImageListSkeleton } from '../components/image-list/ImageListSkeleton'
import { useImageListViewModel } from '../viewmodels/image-list/useImageListViewModel'

interface ImageListPageProps {
  onNavigate: (page: AppPage) => void
}

export function ImageListPage({
  onNavigate,
}: ImageListPageProps) {
  const viewModel = useImageListViewModel()

  return (
    <main className="app-shell">
      <AppHeader
        activePage="list"
        onNavigate={onNavigate}
      />

      <div className="list-layout">
        <section className="list-heading">
          <div>
            <p className="eyebrow">YOUR CREATIONS</p>
            <h1>创作列表</h1>
            <p>浏览已经生成的图片和对应创作信息。</p>
          </div>

          <div className="list-heading-actions">
            <span>共 {viewModel.total} 条</span>
            <button
              type="button"
              onClick={viewModel.refresh}
              disabled={viewModel.isLoading}
            >
              {viewModel.isLoading ? '加载中…' : '刷新'}
            </button>
          </div>
        </section>

        {viewModel.isLoading && viewModel.items.length === 0 ? (
          <ImageListSkeleton />
        ) : viewModel.errorMessage && viewModel.items.length === 0 ? (
          <section className="list-error" role="alert">
            <h2>历史记录加载失败</h2>
            <p>{viewModel.errorMessage}</p>
            <button type="button" onClick={viewModel.refresh}>
              重新加载
            </button>
          </section>
        ) : viewModel.items.length === 0 ? (
          <ImageListEmpty
            onCreate={() => onNavigate('create')}
          />
        ) : (
          <>
            {viewModel.errorMessage && (
              <p className="error-message" role="alert">
                {viewModel.errorMessage}
              </p>
            )}

            <section
              className={
                viewModel.isLoading
                  ? 'generation-grid is-refreshing'
                  : 'generation-grid'
              }
              aria-label="图片创作历史"
            >
              {viewModel.items.map((generation) => (
                <ImageGenerationCard
                  key={generation.id}
                  generation={generation}
                />
              ))}
            </section>

            <ImageListPagination
              currentPage={viewModel.currentPage}
              totalPages={viewModel.totalPages}
              canGoPrevious={viewModel.canGoPrevious}
              canGoNext={viewModel.canGoNext}
              onPrevious={viewModel.goToPreviousPage}
              onNext={viewModel.goToNextPage}
            />
          </>
        )}
      </div>
    </main>
  )
}
