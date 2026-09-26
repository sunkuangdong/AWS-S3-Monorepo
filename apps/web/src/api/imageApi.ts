import type {
    AnalyzeImageRequest,
    AnalyzeImageResponse,
    ApiErrorResponse,
    PresignUploadRequest,
    PresignUploadResponse,
} from "../types/image"

/**
 * FastAPI 服务的基础地址。
 * Base URL of the FastAPI service.
 *
 * 开发环境中来自：
 * In development, it comes from:
 * apps/web/.env
 *
 * VITE_API_BASE_URL=http://localhost:8000
 */
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(
    /\/+$/,
    '',
)

if (!apiBaseUrl) {
    throw new Error(
        "缺少环境变量 VITE_API_BASE_URL"
    )
}

/**
 * 从 FastAPI 错误响应中读取可显示的信息。
 * Read a displayable message from a FastAPI error response.
 *
 * @param response FastAPI 返回的 HTTP 响应。 / HTTP response returned by FastAPI.
 * @returns 后端 detail 或 HTTP 状态信息。 / Backend detail or an HTTP status message.
 */
async function readApiError(
    response: Response,
): Promise<string> {
    try {
        const errorData = (await response.json()) as ApiErrorResponse
        if (errorData.detail) {
            return errorData.detail
        }
    } catch {
        // 响应不是 JSON 时，继续使用下面的默认错误信息。
        // Fall back to the default message when the response is not JSON.
    }

    return `请求失败：HTTP ${response.status}`
}

/**
 * 向 FastAPI 申请临时 S3 上传凭证。
 * Request temporary S3 upload credentials from FastAPI.
 *
 * 此函数只申请凭证，不上传图片。
 * This function obtains credentials but does not upload the image.
 */
export async function createPresignedUpload(
    request: PresignUploadRequest,
): Promise<PresignUploadResponse> {
    const response = await fetch(
        `${apiBaseUrl}/api/v1/images/presign-upload`,
        {
            method: "POST",
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        }
    )
    if (!response.ok) {
        throw new Error(
        await readApiError(response),
        )
    }

    return (await response.json()) as PresignUploadResponse
}

/**
 * 使用预签名表单把浏览器中的文件直接上传到 S3。
 * Upload a browser File directly to S3 with a presigned form.
 *
 * 不要手动设置 Content-Type 请求头；浏览器会为 FormData
 * 自动生成包含 boundary 的正确请求头。
 * Do not set the Content-Type header manually; the browser adds the
 * correct multipart boundary for FormData.
 */
export async function uploadImageToS3(
  file: File,
  upload: PresignUploadResponse,
): Promise<void> {
    const formData = new FormData()

    for (const [name, value] of Object.entries(
        upload.fields,
    )) {
        formData.append(name, value)
    }

    formData.append('file', file)
    const response = await fetch(
        upload.upload_url,
        {
        method: 'POST',
        body: formData,
        },
    )

    if (!response.ok) {
        throw new Error(
        `上传 S3 失败：HTTP ${response.status}`,
        )
  }
}

/**
 * 请求 FastAPI 使用 OpenAI 分析已经上传的图片。
 * Ask FastAPI to analyze an uploaded image with OpenAI.
 */
export async function analyzeImage(
  request: AnalyzeImageRequest,
): Promise<AnalyzeImageResponse> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/images/analyze`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    },
  )

  if (!response.ok) {
    throw new Error(
      await readApiError(response),
    )
  }

  return (await response.json()) as AnalyzeImageResponse
}
