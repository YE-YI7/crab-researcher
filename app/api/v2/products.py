"""Canonical tenant-scoped Product Profile API.

The older ``/competitors/products`` routes remain available for compatibility,
but new product flows should use this surface.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_user
from app.models.schemas import UserProductCreate, UserProductResponse
from app.models.task import UserProduct

router = APIRouter(prefix="/products", tags=["Product Profiles"])


class ProductProfileUpdate(BaseModel):
    product_name: str | None = Field(None, min_length=1, max_length=255)
    industry: str | None = Field(None, min_length=1, max_length=100)
    category: str | None = Field(None, min_length=1, max_length=100)
    keywords: list[str] | None = None
    price_range: dict | None = None
    platforms: list[str] | None = None


async def _owned_product(db: AsyncSession, product_id: int, user_id: int) -> UserProduct:
    result = await db.execute(
        select(UserProduct).where(UserProduct.id == product_id, UserProduct.user_id == user_id)
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("", response_model=UserProductResponse, status_code=201)
async def create_product_profile(
    body: UserProductCreate,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    product = UserProduct(
        user_id=current_user["user_id"],
        product_name=body.product_name,
        industry=body.industry,
        category=body.category,
        keywords=body.keywords or [body.category],
        price_range=body.price_range or {},
        platforms=body.platforms or ["reddit", "hackernews"],
    )
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return product


@router.get("", response_model=list[UserProductResponse])
async def list_product_profiles(
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProduct)
        .where(UserProduct.user_id == current_user["user_id"])
        .order_by(UserProduct.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=UserProductResponse)
async def get_product_profile(
    product_id: int,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await _owned_product(db, product_id, current_user["user_id"])


@router.patch("/{product_id}", response_model=UserProductResponse)
async def update_product_profile(
    product_id: int,
    body: ProductProfileUpdate,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    product = await _owned_product(db, product_id, current_user["user_id"])
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.flush()
    await db.refresh(product)
    return product
