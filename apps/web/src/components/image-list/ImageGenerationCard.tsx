import type { ImageGenerationResponse } from '../../types/image'
import { AppTooltip } from '../ui/AppTooltip'
import { ImageCardActions } from './ImageCardActions'
import { ImageStatusBadge } from './ImageStatusBadge'

interface ImageGenerationCardProps {
  generation: ImageGenerationResponse
  isDownloading?: boolean
  isDeleting?: boolean
  onDownload?: (
    generation: ImageGenerationResponse,
  ) => void
  onDelete?: (
    generation: ImageGenerationResponse,
  ) => void
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
  isDownloading = false,
  isDeleting = false,
  onDownload,
  onDelete,
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
      <div className="generation-image-area">
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

        <ImageCardActions
          prompt={generation.user_prompt}
          canDownload={
            generation.status === 'completed'
            && generation.output_object_key !== null
          }
          isDownloading={isDownloading}
          isDeleting={isDeleting}
          onDownload={
            onDownload
              ? () => onDownload(generation)
              : undefined
          }
          onDelete={
            onDelete
              ? () => onDelete(generation)
              : undefined
          }
        />
      </div>

      <div className="generation-card-content">
        <div className="generation-card-heading">
          <AppTooltip content={generation.user_prompt}>
            <p tabIndex={0}>
              {generation.user_prompt}
            </p>
          </AppTooltip>
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
