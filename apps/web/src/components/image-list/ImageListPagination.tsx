interface ImageListPaginationProps {
  currentPage: number
  totalPages: number
  canGoPrevious: boolean
  canGoNext: boolean
  onPrevious: () => void
  onNext: () => void
}

export function ImageListPagination({
  currentPage,
  totalPages,
  canGoPrevious,
  canGoNext,
  onPrevious,
  onNext,
}: ImageListPaginationProps) {
  if (totalPages === 0) {
    return null
  }

  return (
    <nav className="list-pagination" aria-label="历史记录分页">
      <button
        type="button"
        onClick={onPrevious}
        disabled={!canGoPrevious}
      >
        上一页
      </button>
      <span>
        第 {currentPage} / {totalPages} 页
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={!canGoNext}
      >
        下一页
      </button>
    </nav>
  )
}
