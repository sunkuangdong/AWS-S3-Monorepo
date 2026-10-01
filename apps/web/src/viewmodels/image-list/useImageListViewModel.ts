import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'

import { listImageGenerations } from '../../api/imageApi'
import {
  imageListReducer,
  initialImageListState,
} from './imageListReducer'
import type { ImageListAction } from './imageListReducer'

const pageSize = 20

function getErrorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : '加载历史记录时发生未知错误。'
}

/**
 * 请求一页数据，并将结果转换为 reducer action。
 * Request one page and convert the outcome into a reducer action.
 */
async function requestPage(
  offset: number,
): Promise<ImageListAction> {
  try {
    const response = await listImageGenerations(
      pageSize,
      offset,
    )

    return {
      type: 'loadSucceeded',
      payload: response,
    }
  } catch (error) {
    return {
      type: 'loadFailed',
      payload: getErrorMessage(error),
    }
  }
}

/**
 * 历史创作列表的 ViewModel。
 * ViewModel for the image-generation history list.
 *
 * 只负责协调数据请求、状态转换和页面命令。
 * Only coordinates requests, state transitions, and view commands.
 */
export function useImageListViewModel() {
  const [state, dispatch] = useReducer(
    imageListReducer,
    initialImageListState,
  )
  const latestRequestId = useRef(0)

  const loadPage = useCallback(
    async (offset: number): Promise<void> => {
      const requestId = latestRequestId.current + 1
      latestRequestId.current = requestId

      dispatch({ type: 'loadStarted' })
      const action = await requestPage(offset)

      if (requestId === latestRequestId.current) {
        dispatch(action)
      }
    },
    [],
  )

  useEffect(() => {
    let isCancelled = false
    const requestId = latestRequestId.current + 1

    latestRequestId.current = requestId

    void requestPage(0).then((action) => {
      if (
        !isCancelled
        && requestId === latestRequestId.current
      ) {
        dispatch(action)
      }
    })

    return () => {
      isCancelled = true
    }
  }, [])

  const totalPages =
    state.total === 0
      ? 0
      : Math.ceil(state.total / state.limit)

  const currentPage =
    state.total === 0
      ? 0
      : Math.floor(state.offset / state.limit) + 1

  const canGoPrevious =
    state.offset > 0 && !state.isLoading

  const canGoNext =
    state.offset + state.limit < state.total
    && !state.isLoading

  const goToPreviousPage = useCallback((): void => {
    if (!canGoPrevious) {
      return
    }

    void loadPage(
      Math.max(0, state.offset - state.limit),
    )
  }, [canGoPrevious, loadPage, state.limit, state.offset])

  const goToNextPage = useCallback((): void => {
    if (!canGoNext) {
      return
    }

    void loadPage(state.offset + state.limit)
  }, [canGoNext, loadPage, state.limit, state.offset])

  const refresh = useCallback((): void => {
    void loadPage(state.offset)
  }, [loadPage, state.offset])

  return {
    ...state,
    currentPage,
    totalPages,
    canGoPrevious,
    canGoNext,
    goToPreviousPage,
    goToNextPage,
    refresh,
  }
}
