"""
竞品管理 API
- 核心: 用户手动添加/更新/删除竞品品牌
- 辅助: LLM 自动发现竞品候选（可选）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_user
from app.models.task import UserProduct, CompetitorDiscovery, CompetitorProduct
from app.models.schemas import (
    UserProductCreate, UserProductResponse,
    CompetitorProductCreate, CompetitorProductUpdate, CompetitorProductResponse,
    CompetitorDiscoveryResponse, CompetitorConfirmAction,
    MessageResponse,
)
from app.services.competitor_discovery import CompetitorDiscoveryService

router = APIRouter(prefix="/competitors", tags=["竞品管理"])


# ========== 用户产品 ==========

@router.post("/products", response_model=UserProductResponse, summary="创建用户产品")
async def create_product(
    body: UserProductCreate,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """创建你的产品信息，作为竞品管理的起点"""
    product = UserProduct(
        user_id=current_user["user_id"],
        product_name=body.product_name,
        industry=body.industry,
        category=body.category,
        keywords=body.keywords or [body.category],
        price_range=body.price_range or {},
        platforms=body.platforms or ["jd", "tmall"],
    )
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return product


@router.get("/products", response_model=list[UserProductResponse], summary="获取我的产品列表")
async def list_products(
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProduct)
        .where(UserProduct.user_id == current_user["user_id"])
        .order_by(UserProduct.created_at.desc())
    )
    return list(result.scalars().all())


# ========== 竞品手动管理（核心）==========

@router.post("/products/{product_id}/competitors", response_model=CompetitorProductResponse,
             summary="手动添加竞品")
async def add_competitor(
    product_id: int,
    body: CompetitorProductCreate,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """用户自主输入竞品品牌和产品信息"""
    product = await _get_user_product(db, product_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    competitor = await service.add_competitor(product.id, body.model_dump())
    await db.commit()
    return competitor


@router.get("/products/{product_id}/competitors", response_model=list[CompetitorProductResponse],
            summary="获取竞品列表")
async def list_competitors(
    product_id: int,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某产品下所有竞品（用户手动添加 + LLM发现后确认的）"""
    await _get_user_product(db, product_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    return await service.list_competitors(product_id)


@router.put("/competitors/{competitor_id}", response_model=CompetitorProductResponse,
            summary="更新竞品信息")
async def update_competitor(
    competitor_id: int,
    body: CompetitorProductUpdate,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """更新竞品的品牌、价格、链接等信息"""
    await _verify_competitor_ownership(db, competitor_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    update_data = body.model_dump(exclude_unset=True)
    try:
        competitor = await service.update_competitor(competitor_id, update_data)
        await db.commit()
        return competitor
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/competitors/{competitor_id}", response_model=MessageResponse,
               summary="删除竞品")
async def delete_competitor(
    competitor_id: int,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """删除一个竞品"""
    await _verify_competitor_ownership(db, competitor_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    try:
        await service.delete_competitor(competitor_id)
        await db.commit()
        return MessageResponse(message="竞品已删除")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== LLM 自动发现（可选辅助）==========

@router.post("/products/{product_id}/discover", summary="[可选] LLM 自动发现竞品候选")
async def discover_competitors(
    product_id: int,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """
    基于产品的行业/品类信息，让 LLM 自动推荐竞品候选。
    发现的候选需要用户确认后才会进入竞品列表。
    这是一个辅助功能，用户也可以完全手动添加竞品。
    """
    product = await _get_user_product(db, product_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    discoveries = await service.discover(product, current_user["user_id"])
    await db.commit()

    return {
        "message": f"LLM 发现 {len(discoveries)} 个竞品候选，请审核后确认",
        "product": product.product_name,
        "candidates": [
            CompetitorDiscoveryResponse.model_validate(d) for d in discoveries
        ],
    }


@router.get("/products/{product_id}/candidates", response_model=list[CompetitorDiscoveryResponse],
            summary="[可选] 获取 LLM 发现的竞品候选列表")
async def get_candidates(
    product_id: int,
    status: str = Query(None, description="按状态筛选: pending / confirmed / rejected"),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_product(db, product_id, current_user["user_id"])

    service = CompetitorDiscoveryService(db)
    return await service.get_candidates(product_id, status)


@router.put("/candidates/{candidate_id}", response_model=MessageResponse,
            summary="[可选] 确认/排除 LLM 发现的竞品候选")
async def update_candidate(
    candidate_id: int,
    body: CompetitorConfirmAction,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """确认(confirm)则自动添加到竞品列表，排除(reject)则忽略"""
    service = CompetitorDiscoveryService(db)

    try:
        if body.action == "confirm":
            competitor = await service.confirm_candidate(candidate_id)
            await db.commit()
            return MessageResponse(
                message=f"已确认竞品: {competitor.brand} - {competitor.product_name}",
                data=CompetitorProductResponse.model_validate(competitor).model_dump(),
            )
        else:
            await service.reject_candidate(candidate_id)
            await db.commit()
            return MessageResponse(message="已排除该竞品候选")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/candidates/batch-confirm", response_model=MessageResponse,
             summary="[可选] 批量确认所有 pending 候选")
async def batch_confirm(
    product_id: int = Query(..., description="产品ID"),
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """一键确认某产品下所有 pending 状态的竞品候选"""
    service = CompetitorDiscoveryService(db)
    candidates = await service.get_candidates(product_id, status="pending")

    confirmed = []
    for c in candidates:
        competitor = await service.confirm_candidate(c.id)
        confirmed.append(f"{competitor.brand} - {competitor.product_name}")

    await db.commit()
    return MessageResponse(
        message=f"已批量确认 {len(confirmed)} 个竞品",
        data=confirmed,
    )


# ========== 内部辅助 ==========

async def _get_user_product(db: AsyncSession, product_id: int, user_id: int) -> UserProduct:
    """验证产品存在且属于当前用户"""
    result = await db.execute(
        select(UserProduct).where(
            UserProduct.id == product_id,
            UserProduct.user_id == user_id,
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    return product


async def _verify_competitor_ownership(db: AsyncSession, competitor_id: int, user_id: int):
    """验证竞品记录属于当前用户（通过 user_product 关联）"""
    result = await db.execute(
        select(CompetitorProduct)
        .join(UserProduct, CompetitorProduct.user_product_id == UserProduct.id)
        .where(
            CompetitorProduct.id == competitor_id,
            UserProduct.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="竞品不存在")
