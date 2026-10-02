import { AlertDialog } from 'radix-ui'

interface DeleteGenerationDialogProps {
  prompt: string
  isDeleting: boolean
  onConfirm?: () => void
}

function TrashIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M4 7h16" />
      <path d="M9 7V4h6v3" />
      <path d="m6.5 7 .8 13h9.4l.8-13" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  )
}

/**
 * 删除创作记录前的确认对话框。
 * Confirmation dialog shown before deleting a generation.
 */
export function DeleteGenerationDialog({
  prompt,
  isDeleting,
  onConfirm,
}: DeleteGenerationDialogProps) {
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger asChild>
        <button
          className="image-action-button is-delete"
          type="button"
          disabled={isDeleting || !onConfirm}
          aria-label="删除这条创作记录"
        >
          <TrashIcon />
          <span>{isDeleting ? '删除中' : '删除'}</span>
        </button>
      </AlertDialog.Trigger>

      <AlertDialog.Portal>
        <AlertDialog.Overlay className="delete-dialog-overlay" />
        <AlertDialog.Content className="delete-dialog-content">
          <p className="section-kicker">删除创作</p>
          <AlertDialog.Title className="delete-dialog-title">
            确定删除这条记录吗？
          </AlertDialog.Title>
          <AlertDialog.Description className="delete-dialog-description">
            删除后不会再出现在创作列表中。数据库记录和 S3
            图片仍会保留。
          </AlertDialog.Description>
          <p className="delete-dialog-prompt">
            {prompt}
          </p>

          <div className="delete-dialog-actions">
            <AlertDialog.Cancel asChild>
              <button
                className="dialog-button is-cancel"
                type="button"
                disabled={isDeleting}
              >
                取消
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                className="dialog-button is-confirm"
                type="button"
                onClick={onConfirm}
                disabled={isDeleting || !onConfirm}
              >
                {isDeleting ? '正在删除…' : '确认删除'}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
