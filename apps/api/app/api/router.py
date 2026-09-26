from fastapi import APIRouter

from app.api.routes.images import router as images_router

# 创建 API 总路由。
# Create the top-level API router.
#
# 所有注册到这里的业务接口，
# 都会统一添加 /api/v1 前缀。
# Every business endpoint registered here receives the /api/v1 prefix.
api_router = APIRouter(
    prefix="/api/v1",
)

# 注册图片模块的路由。
# Register the image router.
api_router.include_router(images_router)
