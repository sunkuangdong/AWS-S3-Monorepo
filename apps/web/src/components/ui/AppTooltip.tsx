import type { ReactElement } from 'react'
import { Tooltip as TooltipPrimitive } from 'radix-ui'

interface AppTooltipProps {
  content: string
  children: ReactElement
}

/**
 * 应用统一的悬浮提示组件。
 * Shared tooltip component for the application.
 */
export function AppTooltip({
  content,
  children,
}: AppTooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>
        {children}
      </TooltipPrimitive.Trigger>

      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="app-tooltip-content"
          side="top"
          align="start"
          sideOffset={10}
          collisionPadding={12}
        >
          {content}
          <TooltipPrimitive.Arrow
            className="app-tooltip-arrow"
            width={12}
            height={6}
          />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
