import { describe, expect, it } from 'vitest'

import {
  imageListReducer,
  initialImageListState,
} from './imageListReducer'
import type { ImageGenerationResponse } from '../../types/image'

const generation: ImageGenerationResponse = {
  id: '4bd5968e-f5a5-498a-a184-53861c337681',
  user_prompt: 'A lighthouse in a storm',
  image_analysis: null,
  final_prompt: 'A lighthouse in a storm',
  generation_type: 'text_to_image',
  input_object_key: null,
  output_object_key: 'generated/lighthouse.png',
  output_url: 'https://example.test/lighthouse.png',
  width: 1024,
  height: 1024,
  status: 'completed',
  created_at: '2026-10-12T12:00:00Z',
}

describe('imageListReducer', () => {
  it('stores a successful page response', () => {
    const state = imageListReducer(
      { ...initialImageListState, errorMessage: 'previous error' },
      {
        type: 'loadSucceeded',
        payload: {
          items: [generation],
          total: 21,
          limit: 20,
          offset: 0,
        },
      },
    )

    expect(state.items).toEqual([generation])
    expect(state.total).toBe(21)
    expect(state.isLoading).toBe(false)
    expect(state.errorMessage).toBe('')
  })

  it('preserves current items when refreshing fails', () => {
    const state = imageListReducer(
      { ...initialImageListState, items: [generation] },
      { type: 'loadFailed', payload: 'network unavailable' },
    )

    expect(state.items).toEqual([generation])
    expect(state.isLoading).toBe(false)
    expect(state.errorMessage).toBe('network unavailable')
  })

  it('clears pending action state after an action failure', () => {
    const downloading = imageListReducer(initialImageListState, {
      type: 'downloadStarted',
      payload: generation.id,
    })
    const failed = imageListReducer(downloading, {
      type: 'actionFailed',
      payload: 'download failed',
    })

    expect(failed.downloadingGenerationId).toBeNull()
    expect(failed.deletingGenerationId).toBeNull()
    expect(failed.actionErrorMessage).toBe('download failed')
  })
})
