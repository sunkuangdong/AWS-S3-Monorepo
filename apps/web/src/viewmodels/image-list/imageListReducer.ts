import type {
  ImageGenerationListResponse,
  ImageGenerationResponse,
} from '../../types/image'

export interface ImageListState {
  items: ImageGenerationResponse[]
  total: number
  limit: number
  offset: number
  isLoading: boolean
  errorMessage: string
  actionErrorMessage: string
  downloadingGenerationId: string | null
  deletingGenerationId: string | null
}

export type ImageListAction =
  | { type: 'loadStarted' }
  | {
      type: 'loadSucceeded'
      payload: ImageGenerationListResponse
    }
  | {
      type: 'loadFailed'
      payload: string
    }
  | {
      type: 'downloadStarted'
      payload: string
    }
  | { type: 'downloadFinished' }
  | {
      type: 'deleteStarted'
      payload: string
    }
  | { type: 'deleteFinished' }
  | {
      type: 'actionFailed'
      payload: string
    }

export const initialImageListState: ImageListState = {
  items: [],
  total: 0,
  limit: 20,
  offset: 0,
  isLoading: true,
  errorMessage: '',
  actionErrorMessage: '',
  downloadingGenerationId: null,
  deletingGenerationId: null,
}

/**
 * 根据动作计算历史列表的下一个状态。
 * Calculate the next history-list state from an action.
 */
export function imageListReducer(
  state: ImageListState,
  action: ImageListAction,
): ImageListState {
  switch (action.type) {
    case 'loadStarted':
      return {
        ...state,
        isLoading: true,
        errorMessage: '',
      }

    case 'loadSucceeded':
      return {
        ...state,
        ...action.payload,
        isLoading: false,
        errorMessage: '',
      }

    case 'loadFailed':
      return {
        ...state,
        isLoading: false,
        errorMessage: action.payload,
      }

    case 'downloadStarted':
      return {
        ...state,
        actionErrorMessage: '',
        downloadingGenerationId: action.payload,
      }

    case 'downloadFinished':
      return {
        ...state,
        downloadingGenerationId: null,
      }

    case 'deleteStarted':
      return {
        ...state,
        actionErrorMessage: '',
        deletingGenerationId: action.payload,
      }

    case 'deleteFinished':
      return {
        ...state,
        deletingGenerationId: null,
      }

    case 'actionFailed':
      return {
        ...state,
        actionErrorMessage: action.payload,
        downloadingGenerationId: null,
        deletingGenerationId: null,
      }
  }
}
