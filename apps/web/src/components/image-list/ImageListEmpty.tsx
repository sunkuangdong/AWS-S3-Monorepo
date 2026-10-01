interface ImageListEmptyProps {
  onCreate: () => void
}

export function ImageListEmpty({
  onCreate,
}: ImageListEmptyProps) {
  return (
    <section className="list-empty">
      <span aria-hidden="true">✦</span>
      <h2>还没有创作记录</h2>
      <p>完成第一张 AI 图片后，它会出现在这里。</p>
      <button type="button" onClick={onCreate}>
        开始创作
      </button>
    </section>
  )
}
