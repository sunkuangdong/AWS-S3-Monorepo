class ApplicationError(Exception):
    """
    项目中所有自定义异常的父类。
    Base class for all custom application exceptions.

    通过统一父类，可以区分：
    - 我们主动定义的业务错误
    - Python 或第三方库抛出的系统错误
    A shared base class distinguishes expected business errors from
    exceptions raised by Python or third-party libraries.
    """

class StorageError(ApplicationError):
    """
    S3 存储操作失败时抛出。
    Raised when an S3 storage operation fails.

    示例 / Examples:
    - AWS 凭证错误
    - IAM 权限不足
    - Bucket 不存在
    - 生成预签名地址失败
    - Invalid AWS credentials
    - Insufficient IAM permissions
    - Missing bucket
    - Presigned URL generation failure
    """

class VisionModelError(ApplicationError):
    """
    OpenAI 图片分析失败时抛出。
    Raised when OpenAI image analysis fails.

    示例 / Examples:
    - OpenAI API Key 无效
    - API 余额不足
    - 模型名称错误
    - OpenAI 无法读取图片
    - Invalid OpenAI API key
    - Insufficient API balance
    - Invalid model name
    - OpenAI cannot retrieve the image
    """

class InvalidObjectKeyError(ApplicationError):
    """
    S3 object key 不符合项目规则时抛出。
    Raised when an S3 object key violates application rules.

    当前项目只允许操作 uploads/ 目录中的对象。
    The current application only accepts objects below uploads/.
    """

class ImageGenerationError(ApplicationError):
    """
    OpenAI 图片生成失败时抛出。
    Raised when OpenAI image generation fails.

    示例 / Examples:
    - API Key 无效
    - 账户额度不足
    - 模型不可用
    - 提示词被安全策略拒绝
    - OpenAI 没有返回图片数据
    - Invalid API key
    - Insufficient account quota
    - Unavailable model
    - Prompt rejected by safety policies
    - Missing image data in the OpenAI response
    """