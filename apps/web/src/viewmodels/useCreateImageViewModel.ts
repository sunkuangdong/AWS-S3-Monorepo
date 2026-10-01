import {
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  createImageGeneration,
  createPresignedUpload,
  uploadImageToS3,
} from '../api/imageApi'
import type {
  ImageContentType,
  ImageGenerationResponse,
} from '../types/image'

/**
 * 创作页支持的参考图类型。
 * Reference-image types supported by the creation page.
 */
const supportedImageTypes: ImageContentType[] = [
  'image/jpeg',
  'image/png',
  'image/webp',
]

const maxUploadBytes = 10 * 1024 * 1024
const defaultPrompt = '一只橘猫坐在窗台上，温暖的晨光'

function isSupportedImageType(
  type: string,
): type is ImageContentType {
  return supportedImageTypes.includes(
    type as ImageContentType,
  )
}

/**
 * 创作页的 ViewModel。
 * ViewModel for the creation page.
 *
 * View 只绑定这里的状态和命令，不直接调用 API。
 * The View binds to this state and these commands without calling APIs.
 */
export function useCreateImageViewModel() {
  const [prompt, setPrompt] = useState(defaultPrompt)
  const [selectedFile, setSelectedFile] =
    useState<File | null>(null)
  const [previewUrl, setPreviewUrl] =
    useState<string | null>(null)
  const [result, setResult] =
    useState<ImageGenerationResponse | null>(null)
  const [statusMessage, setStatusMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const previewUrlRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current)
      }
    }
  }, [])

  function releasePreviewUrl(): void {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = null
    }
  }

  function selectFile(file: File | null): void {
    setErrorMessage('')
    setStatusMessage('')
    setResult(null)
    releasePreviewUrl()

    if (!file) {
      setSelectedFile(null)
      setPreviewUrl(null)
      return
    }

    if (!isSupportedImageType(file.type)) {
      setSelectedFile(null)
      setPreviewUrl(null)
      setErrorMessage('只支持 JPG、PNG 和 WebP 图片。')
      return
    }

    if (file.size > maxUploadBytes) {
      setSelectedFile(null)
      setPreviewUrl(null)
      setErrorMessage('图片不能超过 10MB。')
      return
    }

    const objectUrl = URL.createObjectURL(file)

    previewUrlRef.current = objectUrl
    setSelectedFile(file)
    setPreviewUrl(objectUrl)
  }

  function removeFile(): void {
    selectFile(null)
  }

  async function generate(): Promise<void> {
    const normalizedPrompt = prompt.trim()

    if (!normalizedPrompt) {
      setErrorMessage('请输入图片创作要求。')
      return
    }

    setErrorMessage('')
    setResult(null)
    setIsGenerating(true)

    try {
      let inputObjectKey: string | null = null

      if (selectedFile) {
        setStatusMessage('正在上传参考图……')

        const upload = await createPresignedUpload({
          file_name: selectedFile.name,
          content_type: selectedFile.type as ImageContentType,
        })

        await uploadImageToS3(selectedFile, upload)
        inputObjectKey = upload.object_key
        setStatusMessage('正在分析参考图并生成图片……')
      } else {
        setStatusMessage('正在生成图片……')
      }

      const generation = await createImageGeneration({
        prompt: normalizedPrompt,
        input_object_key: inputObjectKey,
        width: 1024,
        height: 1024,
      })

      setResult(generation)
      setStatusMessage('图片生成完成。')
    } catch (error) {
      setStatusMessage('')
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '生成图片时发生未知错误。',
      )
    } finally {
      setIsGenerating(false)
    }
  }

  return {
    prompt,
    selectedFile,
    previewUrl,
    result,
    statusMessage,
    errorMessage,
    isGenerating,
    canGenerate: prompt.trim().length > 0 && !isGenerating,
    setPrompt,
    selectFile,
    removeFile,
    generate,
  }
}
