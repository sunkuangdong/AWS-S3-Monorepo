import type {
    AnalyzeImageRequest,
    AnalyzeImageResponse,
    ApiErrorResponse,
    PresignUploadRequest,
    PresignUploadResponse,
} from "../types/image"

/**
 * FastAPI 服务的基础地址。
 *
 * 开发环境中来自：
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
    }

    return `请求失败：HTTP ${response.status}`
}

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


