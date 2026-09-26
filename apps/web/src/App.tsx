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
 *
 * 这里必须与 FastAPI 后端允许的类型保持一致。
 */
const supportedImageTypes: ImageContentType[] = [
  'image/jpeg',
  'image/png',
  'image/webp',
]

/**
 * 检查浏览器提供的文件类型是否受支持。
 *
 * `type is ImageContentType` 是 TypeScript 类型守卫。
 * 验证成功后，TypeScript 会把 type 当作 ImageContentType。
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
   */
  const [selectedFile, setSelectedFile] =
    useState<File | null>(null)

  /**
   * 本地图片的临时预览地址。
   */
  const [previewUrl, setPreviewUrl] =
    useState<string | null>(null)

  /**
   * 用户发送给 OpenAI 的提示词。
   */
  const [prompt, setPrompt] = useState(
    '请详细描述这张图片的内容。',
  )

  /**
   * FastAPI 返回的图片分析结果。
   */
  const [result, setResult] =
    useState<AnalyzeImageResponse | null>(null)

  /**
   * 当前处理进度。
   */
  const [statusMessage, setStatusMessage] =
    useState('')

  /**
   * 发生错误时显示的信息。
   */
  const [errorMessage, setErrorMessage] =
    useState('')

  /**
   * 表示当前是否正在上传或分析。
   *
   * 处理期间禁用表单，避免用户重复提交。
   */
  const [isProcessing, setIsProcessing] =
    useState(false)

  /**
   * 保存当前预览地址。
   *
   * URL.createObjectURL() 创建的地址会占用浏览器内存，
   * 因此不再使用时需要调用 URL.revokeObjectURL()。
   */
  const previewUrlRef = useRef<string | null>(null)

  /**
   * 组件从页面移除时，释放最后一个图片预览地址。
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
   */
  function handleFileChange(
    event: ChangeEvent<HTMLInputElement>,
  ): void {
    const file = event.target.files?.[0]

    /**
     * 清除上一次的分析结果和错误。
     */
    setResult(null)
    setErrorMessage('')
    setStatusMessage('')

    /**
     * 释放之前创建的本地预览地址。
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
       *
       * 这样用户可以重新选择文件。
       */
      event.target.value = ''
      return
    }

    /**
     * 为本地 File 创建浏览器临时地址，
     * 让图片还没有上传时就可以预览。
     */
    const objectUrl = URL.createObjectURL(file)

    previewUrlRef.current = objectUrl
    setSelectedFile(file)
    setPreviewUrl(objectUrl)
  }

  /**
   * 用户提交表单时执行完整处理流程。
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
       */
      setStatusMessage('正在申请上传凭证……')

      const upload = await createPresignedUpload({
        file_name: selectedFile.name,
        content_type: selectedFile.type,
      })

      /**
       * 第二步：浏览器把图片直接上传到 S3。
       */
      setStatusMessage('正在上传图片……')

      await uploadImageToS3(
        selectedFile,
        upload,
      )

      /**
       * 第三步：把 object_key 发送给 FastAPI。
       *
       * FastAPI 会生成临时读取地址，
       * 然后调用 OpenAI 分析图片。
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