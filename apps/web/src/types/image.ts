/*
 * 后端允许上传的图片 MIME 类型。
 *
 * 必须与 FastAPI 中 PresignUploadRequest.content_type
 * 允许的类型保持一致。
*/
export type ImageContentType = 
    | 'image/jpeg'
    | 'image/png'
    | 'image/webp'

/*
 * 向 FastAPI 申请 S3 上传凭证时发送的数据。
*/
export interface PresignUploadRequest {
    /**
     * 用户选择的原始文件名。
     * 例如：dog.jpg
     */
    file_name: string
    /**
    * 图片的 MIME 类型。
    * 例如：image/jpeg
    */
    content_type: ImageContentType
}

/**
 * FastAPI 返回的 S3 预签名上传信息。
 */
export interface PresignUploadResponse {
    upload_url: string
    fields: Record<string, string>
    object_key: string
    expires_in: number
}

/**
 * 请求 FastAPI 分析图片时发送的数据。
 */
export interface AnalyzeImageRequest {
    object_key: string
    prompt: string
}
/**
 * FastAPI 完成图片分析后返回的数据。
 */
export interface AnalyzeImageResponse {
    object_key: string
    description: string
}
/**
 * FastAPI 返回的常见错误格式。
 *
 * 例如：
 * {
 *   "detail": "不支持的图片格式"
 * }
 */
export interface ApiErrorResponse {
    detail: string
}
