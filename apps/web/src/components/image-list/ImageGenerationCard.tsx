import type { ImageGenerationResponse } from '../../types/image'
import { ImageStatusBadge } from './ImageStatusBadge'

interface ImageGenerationCardProps {
  generation: ImageGenerationResponse
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function getModeLabel(
  generation: ImageGenerationResponse,
): string {
  return generation.generation_type === 'image_to_image'
    ? '参考图生成'
    : '文字生成'
}

export function ImageGenerationCard({
  generation,
}: ImageGenerationCardProps) {
  const imageContent = generation.output_url ? (
    <img
      src={generation.output_url}
      alt={generation.user_prompt}
      loading="lazy"
    />
  ) : (
    <span>
      {generation.status === 'failed'
        ? '生成失败'
        : '图片暂不可用'}
    </span>
  )

  return (
    <article className="generation-card">
      {generation.output_url ? (
        <a
          className="generation-thumbnail"
          href={generation.output_url}
          target="_blank"
          rel="noreferrer"
          aria-label={`打开图片：${generation.user_prompt}`}
        >
          {imageContent}
        </a>
      ) : (
        <div className="generation-thumbnail is-placeholder">
          {imageContent}
        </div>
      )}

      <div className="generation-card-content">
        <div className="generation-card-heading">
          <p>{generation.user_prompt}</p>
          <ImageStatusBadge status={generation.status} />
        </div>

        <dl className="generation-metadata">
          <div>
            <dt>创作模式</dt>
            <dd>{getModeLabel(generation)}</dd>
          </div>
          <div>
            <dt>图片尺寸</dt>
            <dd>{generation.width} × {generation.height}</dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>{dateFormatter.format(new Date(generation.created_at))}</dd>
          </div>
        </dl>
      </div>
    </article>
  )
}
