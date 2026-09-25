from typing import Literal

from pydantic import BaseModel, Field

class PresignUploadRequest(BaseModel):
    """
    前端申请 S3 上传凭证时发送的数据。

    示例:
        {
            "file_name": "dog.jpg",
            "content_type": "image/jpeg"
        }
    """
    file_name: str = Field(
        min_length=1,
        max_length=225,
        description="用户选择的原始文件名",
    )

    content_type: Literal[
        "image/jpeg",
        "image/png",
        "image/webp",
    ]

class PresignUploadResponse(BaseModel):
    """
    FastAPI 返回给调用方的 S3 预签名上传信息。

    upload_url:
        图片需要上传到哪个 S3 地址。

    fields:
        上传时必须一起提交的 AWS 签名字段。

    object_key:
        图片上传完成后在 S3 中的路径。

    expires_in:
        上传凭证有效时间，单位为秒。
    """
    upload_url: str
    fields: dict[str, str]
    object_key: str
    expires_in: int

class AnalyzeImageRequest(BaseModel):
    """
    请求 OpenAI 分析一张已经上传到 S3 的图片。

    示例:
        {
            "object_key": "uploads/abc123.jpg",
            "prompt": "请详细描述这张图片"
        }
    """
    object_key:str = Field(
        min_length=1,
        max_length=1024,
        description="图片在 S3 中的对象路径",
    )
    prompt: str = Field(
        default="请详细描述这张图片的内容。",
        min_length=1,
        max_length=2000,
        description="发送给 OpenAI 的图片分析要求",
    )

class AnalyzeImageResponse(BaseModel):
    """
    OpenAI 图片分析成功后返回的数据。
    """
    object_key: str
    description: str
