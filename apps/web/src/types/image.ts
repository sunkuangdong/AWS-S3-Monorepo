/*
 * 后端允许上传的图片 MIME 类型。
 * Image MIME types accepted by the backend.
 *
 * 必须与 FastAPI 中 PresignUploadRequest.content_type
 * 允许的类型保持一致。
 * This union must match PresignUploadRequest.content_type in FastAPI.
*/
export type ImageContentType = 
    | 'image/jpeg'
    | 'image/png'
    | 'image/webp'

/*
 * 向 FastAPI 申请 S3 上传凭证时发送的数据。
 * Data sent to FastAPI when requesting S3 upload credentials.
*/
export interface PresignUploadRequest {
    /**
     * 用户选择的原始文件名。
     * 例如：dog.jpg
     * Original file name selected by the user, for example dog.jpg.
     */
    file_name: string
    /**
    * 图片的 MIME 类型。
    * 例如：image/jpeg
    * Image MIME type, for example image/jpeg.
    */
    content_type: ImageContentType
}

/**
 * FastAPI 返回的 S3 预签名上传信息。
 * S3 presigned upload information returned by FastAPI.
 */
export interface PresignUploadResponse {
    /** S3 上传地址。 / S3 upload endpoint. */
    upload_url: string

    /** AWS 要求的预签名表单字段。 / Presigned form fields required by AWS. */
    fields: Record<string, string>

    /** 图片在 S3 中的对象路径。 / Image object path in S3. */
    object_key: string

    /** 凭证有效时间（秒）。 / Credential lifetime in seconds. */
    expires_in: number
}

/**
 * 请求 FastAPI 分析图片时发送的数据。
 * Data sent to FastAPI when requesting image analysis.
 */
export interface AnalyzeImageRequest {
    /** 待分析图片的 S3 路径。 / S3 path of the image to analyze. */
    object_key: string

    /** 用户的分析要求。 / User's analysis instruction. */
    prompt: string
}
/**
 * FastAPI 完成图片分析后返回的数据。
 * Data returned after FastAPI completes image analysis.
 */
export interface AnalyzeImageResponse {
    /** 本次结果对应的 S3 路径。 / S3 path associated with this result. */
    object_key: string

    /** OpenAI 返回的图片描述。 / Image description returned by OpenAI. */
    description: string
}

/**
 * 创建图片生成任务时发送的数据。
 * Data sent when creating an image-generation task.
 */
export interface CreateImageGenerationRequest {
    /** 用户的创作描述。 / User's creation prompt. */
    prompt: string

    /** 可选的参考图 S3 路径。 / Optional reference-image S3 path. */
    input_object_key: string | null

    /** 当前版本固定为 1024。 / Fixed to 1024 in the current version. */
    width: 1024

    /** 当前版本固定为 1024。 / Fixed to 1024 in the current version. */
    height: 1024
}

/**
 * 图片生成任务的处理状态。
 * Processing status of an image-generation task.
 */
export type ImageGenerationStatus =
    | 'pending'
    | 'completed'
    | 'failed'

/**
 * 图片生成方式。
 * Image-generation mode.
 */
export type ImageGenerationType =
    | 'text_to_image'
    | 'image_to_image'

/**
 * FastAPI 返回的图片生成记录。
 * Image-generation record returned by FastAPI.
 */
export interface ImageGenerationResponse {
    id: string
    user_prompt: string
    image_analysis: string | null
    final_prompt: string
    generation_type: ImageGenerationType
    input_object_key: string | null
    output_object_key: string | null
    output_url: string | null
    width: number
    height: number
    status: ImageGenerationStatus
    created_at: string
}

/**
 * 图片生成历史列表响应。
 * Image-generation history list response.
 */
export interface ImageGenerationListResponse {
    /** 当前页记录。 / Records on the current page. */
    items: ImageGenerationResponse[]

    /** 全部记录数量。 / Total number of records. */
    total: number

    /** 每页最多返回数量。 / Maximum records per page. */
    limit: number

    /** 跳过的记录数量。 / Number of skipped records. */
    offset: number
}

/**
 * FastAPI 返回的常见错误格式。
 * Common FastAPI error response shape.
 *
 * 例如：
 * Example:
 * {
 *   "detail": "不支持的图片格式"
 * }
 */
export interface ApiErrorResponse {
    /** FastAPI 返回的错误详情。 / Error detail returned by FastAPI. */
    detail: string
}
