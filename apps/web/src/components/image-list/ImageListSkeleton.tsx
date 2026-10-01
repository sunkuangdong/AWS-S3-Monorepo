export function ImageListSkeleton() {
  return (
    <div
      className="generation-grid"
      aria-label="正在加载历史记录"
      aria-busy="true"
    >
      {Array.from({ length: 4 }, (_, index) => (
        <div className="generation-skeleton" key={index}>
          <span />
          <div>
            <i />
            <i />
            <i />
          </div>
        </div>
      ))}
    </div>
  )
}
