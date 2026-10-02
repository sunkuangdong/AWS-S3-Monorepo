import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'

import {
  deleteImageGeneration,
  getImageGenerationDownload,
  listImageGenerations,
} from '../../api/imageApi'
import type { ImageGenerationResponse } from '../../types/image'
import { downloadFileFromUrl } from '../../utils/downloadFile'
import {
  imageListReducer,
  initialImageListState,
} from './imageListReducer'
import type { ImageListAction } from './imageListReducer'

const pageSize = 20

function getErrorMessage(
  error: unknown,
  fallbackMessage = '加载历史记录时发生未知错误。',
): string {
  return error instanceof Error
    ? error.message
    : fallbackMessage
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

  const isActionPending =
    state.downloadingGenerationId !== null
    || state.deletingGenerationId !== null

  const downloadGeneration = useCallback(
    async (
      generation: ImageGenerationResponse,
    ): Promise<void> => {
      if (isActionPending) {
        return
      }

      dispatch({
        type: 'downloadStarted',
        payload: generation.id,
      })

      try {
        const download = await getImageGenerationDownload(
          generation.id,
        )

        downloadFileFromUrl(download.download_url)
        dispatch({ type: 'downloadFinished' })
      } catch (error) {
        dispatch({
          type: 'actionFailed',
          payload: getErrorMessage(
            error,
            '下载图片时发生未知错误。',
          ),
        })
      }
    },
    [isActionPending],
  )

  const deleteGeneration = useCallback(
    async (
      generation: ImageGenerationResponse,
    ): Promise<void> => {
      if (isActionPending) {
        return
      }

      dispatch({
        type: 'deleteStarted',
        payload: generation.id,
      })

      try {
        await deleteImageGeneration(generation.id)

        const nextOffset =
          state.items.length === 1 && state.offset > 0
            ? Math.max(0, state.offset - state.limit)
            : state.offset

        await loadPage(nextOffset)
        dispatch({ type: 'deleteFinished' })
      } catch (error) {
        dispatch({
          type: 'actionFailed',
          payload: getErrorMessage(
            error,
            '删除创作记录时发生未知错误。',
          ),
        })
      }
    },
    [
      isActionPending,
      loadPage,
      state.items.length,
      state.limit,
      state.offset,
    ],
  )

  return {
    ...state,
    currentPage,
    totalPages,
    canGoPrevious,
    canGoNext,
    goToPreviousPage,
    goToNextPage,
    refresh,
    isActionPending,
    downloadGeneration,
    deleteGeneration,
  }
}
