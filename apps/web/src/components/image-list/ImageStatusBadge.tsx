import type { ImageGenerationStatus } from '../../types/image'

interface ImageStatusBadgeProps {
  status: ImageGenerationStatus
}

const statusLabels: Record<ImageGenerationStatus, string> = {
  pending: '处理中',
  completed: '已完成',
  failed: '失败',
}

export function ImageStatusBadge({
  status,
}: ImageStatusBadgeProps) {
  return (
    <span className={`generation-status status-${status}`}>
      {statusLabels[status]}
    </span>
  )
}
