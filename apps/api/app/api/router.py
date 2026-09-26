from fastapi import APIRouter

from app.api.routes.images import router as images_router

# 创建 API 总路由。
#
# 所有注册到这里的业务接口，
# 都会统一添加 /api/v1 前缀。
api_router = APIRouter(
    prefix="/api/v1",
)

# 注册图片模块的路由。
api_router.include_router(images_router)

