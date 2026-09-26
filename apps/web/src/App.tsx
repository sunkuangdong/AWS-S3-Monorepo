import {
  useEffect,
  useRef,
  useState,
} from 'react'
import type {
  ChangeEvent,
  FormEvent,
} from 'react'

import {
  analyzeImage,
  createPresignedUpload,
  uploadImageToS3,
} from './api/imageApi'
import type {
  AnalyzeImageResponse,
  ImageContentType,
} from './types/image'

import './App.css'

/**
 * 前端允许用户选择的图片类型。
 * Image types that users may select in the frontend.
 *
 * 这里必须与 FastAPI 后端允许的类型保持一致。
 * This list must match the types accepted by FastAPI.
 */
const supportedImageTypes: ImageContentType[] = [
  'image/jpeg',
  'image/png',
  'image/webp',
]

/**
 * 检查浏览器提供的文件类型是否受支持。
 * Check whether the browser-provided file type is supported.
 *
 * `type is ImageContentType` 是 TypeScript 类型守卫。
 * 验证成功后，TypeScript 会把 type 当作 ImageContentType。
 * `type is ImageContentType` is a TypeScript type guard. After a
 * successful check, TypeScript treats type as ImageContentType.
 */
function isSupportedImageType(
  type: string,
): type is ImageContentType {
  return supportedImageTypes.includes(
    type as ImageContentType,
  )
}

function App() {
  /**
   * 用户当前选择的本地图片文件。
   * Local image file currently selected by the user.
   */
  const [selectedFile, setSelectedFile] =
    useState<File | null>(null)

  /**
   * 本地图片的临时预览地址。
   * Temporary browser URL used to preview the local image.
   */
  const [previewUrl, setPreviewUrl] =
    useState<string | null>(null)

  /**
   * 用户发送给 OpenAI 的提示词。
   * Prompt that the user sends to OpenAI.
   */
  const [prompt, setPrompt] = useState(
    '请详细描述这张图片的内容。',
  )

  /**
   * FastAPI 返回的图片分析结果。
   * Image analysis result returned by FastAPI.
   */
  const [result, setResult] =
    useState<AnalyzeImageResponse | null>(null)

  /**
   * 当前处理进度。
   * Current processing status.
   */
  const [statusMessage, setStatusMessage] =
    useState('')

  /**
   * 发生错误时显示的信息。
   * Message displayed when an error occurs.
   */
  const [errorMessage, setErrorMessage] =
    useState('')

  /**
   * 表示当前是否正在上传或分析。
   * Indicate whether an upload or analysis is in progress.
   *
   * 处理期间禁用表单，避免用户重复提交。
   * Disable the form during processing to prevent duplicate submissions.
   */
  const [isProcessing, setIsProcessing] =
    useState(false)

  /**
   * 保存当前预览地址。
   * Store the current preview URL.
   *
   * URL.createObjectURL() 创建的地址会占用浏览器内存，
   * 因此不再使用时需要调用 URL.revokeObjectURL()。
   * URLs created by URL.createObjectURL() consume browser resources,
   * so URL.revokeObjectURL() releases them when they are no longer used.
   */
  const previewUrlRef = useRef<string | null>(null)

  /**
   * 组件从页面移除时，释放最后一个图片预览地址。
   * Release the last preview URL when the component unmounts.
   */
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(
          previewUrlRef.current,
        )
      }
    }
  }, [])

  /**
   * 用户选择图片时执行。
   * Run when the user selects an image.
   */
  function handleFileChange(
    event: ChangeEvent<HTMLInputElement>,
  ): void {
    const file = event.target.files?.[0]

    /**
     * 清除上一次的分析结果和错误。
     * Clear the previous analysis result and error.
     */
    setResult(null)
    setErrorMessage('')
    setStatusMessage('')

    /**
     * 释放之前创建的本地预览地址。
     * Release the previously created local preview URL.
     */
    if (previewUrlRef.current) {
      URL.revokeObjectURL(
        previewUrlRef.current,
      )
      previewUrlRef.current = null
    }

    if (!file) {
      setSelectedFile(null)
      setPreviewUrl(null)
      return
    }

    if (!isSupportedImageType(file.type)) {
      setSelectedFile(null)
      setPreviewUrl(null)
      setErrorMessage(
        '只支持 JPG、PNG 和 WebP 图片。',
      )

      /**
       * 清空文件输入框。
       * Clear the file input.
       *
       * 这样用户可以重新选择文件。
       * This lets the user select a file again.
       */
      event.target.value = ''
      return
    }

    /**
     * 为本地 File 创建浏览器临时地址，
     * 让图片还没有上传时就可以预览。
     * Create a temporary browser URL for the local File so the image
     * can be previewed before upload.
     */
    const objectUrl = URL.createObjectURL(file)

    previewUrlRef.current = objectUrl
    setSelectedFile(file)
    setPreviewUrl(objectUrl)
  }

  /**
   * 用户提交表单时执行完整处理流程。
   * Run the complete workflow when the user submits the form.
   */
  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault()

    setErrorMessage('')
    setResult(null)

    if (!selectedFile) {
      setErrorMessage('请先选择一张图片。')
      return
    }

    if (!isSupportedImageType(selectedFile.type)) {
      setErrorMessage(
        '只支持 JPG、PNG 和 WebP 图片。',
      )
      return
    }

    const normalizedPrompt = prompt.trim()

    if (!normalizedPrompt) {
      setErrorMessage('请输入图片分析要求。')
      return
    }

    setIsProcessing(true)

    try {
      /**
       * 第一步：向 FastAPI 申请 S3 上传凭证。
       * Step 1: Request S3 upload credentials from FastAPI.
       */
      setStatusMessage('正在申请上传凭证……')

      const upload = await createPresignedUpload({
        file_name: selectedFile.name,
        content_type: selectedFile.type,
      })

      /**
       * 第二步：浏览器把图片直接上传到 S3。
       * Step 2: Upload the image directly from the browser to S3.
       */
      setStatusMessage('正在上传图片……')

      await uploadImageToS3(
        selectedFile,
        upload,
      )

      /**
       * 第三步：把 object_key 发送给 FastAPI。
       * Step 3: Send the object key to FastAPI.
       *
       * FastAPI 会生成临时读取地址，
       * 然后调用 OpenAI 分析图片。
       * FastAPI creates a temporary read URL and asks OpenAI
       * to analyze the image.
       */
      setStatusMessage('OpenAI 正在分析图片……')

      const analysis = await analyzeImage({
        object_key: upload.object_key,
        prompt: normalizedPrompt,
      })

      setResult(analysis)
      setStatusMessage('分析完成。')
    } catch (error) {
      /**
       * JavaScript 的 catch 变量可能不是 Error 对象，
       * 因此需要先判断类型。
       * A JavaScript catch value is not guaranteed to be an Error,
       * so check its type first.
       */
      if (error instanceof Error) {
        setErrorMessage(error.message)
      } else {
        setErrorMessage(
          '处理图片时发生未知错误。',
        )
      }

      setStatusMessage('')
    } finally {
      /**
       * 无论成功还是失败，都恢复按钮状态。
       * Restore the button state after either success or failure.
       */
      setIsProcessing(false)
    }
  }

  return (
    <main className="app">
      <section className="image-workspace">
        <header className="page-header">
          <h1>AI 图片分析</h1>
          <p>
            上传一张图片，让 OpenAI 分析图片内容。
          </p>
        </header>

        <form
          className="image-form"
          onSubmit={handleSubmit}
        >
          <label htmlFor="image-file">
            选择图片
          </label>

          <input
            id="image-file"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            disabled={isProcessing}
          />

          {selectedFile && (
            <p className="file-information">
              已选择：{selectedFile.name}
            </p>
          )}

          {previewUrl && (
            <div className="preview-container">
              <img
                src={previewUrl}
                alt="待分析图片预览"
                className="image-preview"
              />
            </div>
          )}

          <label htmlFor="analysis-prompt">
            分析要求
          </label>

          <textarea
            id="analysis-prompt"
            value={prompt}
            onChange={(event) =>
              setPrompt(event.target.value)
            }
            rows={5}
            maxLength={2000}
            disabled={isProcessing}
          />

          <button
            type="submit"
            disabled={
              isProcessing || !selectedFile
            }
          >
            {isProcessing
              ? '正在处理……'
              : '上传并分析'}
          </button>
        </form>

        {statusMessage && (
          <p
            className="status-message"
            aria-live="polite"
          >
            {statusMessage}
          </p>
        )}

        {errorMessage && (
          <p
            className="error-message"
            role="alert"
          >
            {errorMessage}
          </p>
        )}

        {result && (
          <section className="analysis-result">
            <h2>分析结果</h2>

            <p>{result.description}</p>

            <details>
              <summary>图片存储信息</summary>
              <code>{result.object_key}</code>
            </details>
          </section>
        )}
      </section>
    </main>
  )
}

export default App
