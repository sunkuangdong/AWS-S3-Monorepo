import { DeleteGenerationDialog } from './DeleteGenerationDialog'

interface ImageCardActionsProps {
  prompt: string
  canDownload: boolean
  isDownloading?: boolean
  isDeleting?: boolean
  isDisabled?: boolean
  onDownload?: () => void
  onDelete?: () => void
}

function DownloadIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 20h14" />
    </svg>
  )
}

/**
 * 图片缩略图上的悬浮操作层。
 * Hover action layer displayed over an image thumbnail.
 */
export function ImageCardActions({
  prompt,
  canDownload,
  isDownloading = false,
  isDeleting = false,
  isDisabled = false,
  onDownload,
  onDelete,
}: ImageCardActionsProps) {
  return (
    <div className="image-card-actions" aria-label="图片操作">
      <button
        className="image-action-button is-download"
        type="button"
        onClick={onDownload}
        disabled={
          !canDownload
          || isDisabled
          || isDownloading
          || !onDownload
        }
        aria-label="下载生成图片"
      >
        <DownloadIcon />
        <span>{isDownloading ? '下载中' : '下载'}</span>
      </button>

      <DeleteGenerationDialog
        prompt={prompt}
        isDeleting={isDeleting}
        isDisabled={isDisabled}
        onConfirm={onDelete}
      />
    </div>
  )
}
