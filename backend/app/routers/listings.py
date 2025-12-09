from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload 

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import Settings
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_marketplace import ListingMarketplace # [추가] 연결 정보 저장을 위해 필요
from app.schemas.listing import ListingCreate, ListingRead, ListingUpdate

router = APIRouter(prefix="/listings", tags=["listings"])

settings = Settings()


def _attach_thumbnail(listing: Listing) -> ListingRead:
    """
    SQLAlchemy Listing 객체를 ListingRead로 변환하면서
    대표 이미지(thumbnail_url)를 붙여주는 헬퍼 함수.
    """
    # model_validate를 호출할 때, 이미 로딩된 marketplace_links 정보도 같이 변환됩니다.
    data = ListingRead.model_validate(listing)

    # Listing.images 관계에 이미지가 있으면 첫 번째 것을 썸네일로 사용
    if getattr(listing, "images", None):
        if listing.images:
            first_img = listing.images[0]
            data.thumbnail_url = f"{settings.media_url}/{first_img.file_path}"

    return data


@router.get("/", response_model=List[ListingRead])
def list_listings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listings = (
        db.query(Listing)
        .filter(Listing.owner_id == current_user.id)
        # [중요] 이미지와 마켓플레이스 연동 정보를 함께 가져옵니다.
        .options(selectinload(Listing.images))
        .options(selectinload(Listing.marketplace_links))
        .order_by(Listing.created_at.desc())
        .all()
    )

    # 썸네일까지 포함된 ListingRead 리스트로 변환
    return [_attach_thumbnail(l) for l in listings]


@router.post("/", response_model=ListingRead, status_code=status.HTTP_201_CREATED)
def create_listing(
    listing_in: ListingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. DB 모델에 없는 필드(import용) 분리
    listing_data = listing_in.model_dump(exclude={
        "import_from_marketplace", 
        "import_external_id", 
        "import_url"
    })
    
    # 2. Listing 생성 (sku, condition 포함)
    listing = Listing(
        **listing_data,
        owner_id=current_user.id
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    # 3. [Import 로직] eBay에서 가져온 경우 연결 정보 자동 생성
    if listing_in.import_from_marketplace:
        marketplace = listing_in.import_from_marketplace
        
        # 중복 방지 (혹시나 해서 체크)
        existing_link = db.query(ListingMarketplace).filter(
            ListingMarketplace.listing_id == listing.id,
            ListingMarketplace.marketplace == marketplace
        ).first()

        if not existing_link:
            new_link = ListingMarketplace(
                listing_id=listing.id,
                marketplace=marketplace,
                status="published", # Import 된 것은 이미 발행된 상태
                external_item_id=listing_in.import_external_id,
                external_url=listing_in.import_url,
                sku=listing.sku,    # Listing에 저장된 SKU 사용
                offer_id=None       # Offer ID는 알 수 없으므로 비워둠
            )
            db.add(new_link)
            db.commit()
            
            # 연결 정보 포함하여 리스팅 다시 로딩
            db.refresh(listing)

    return _attach_thumbnail(listing)


def _get_owned_listing_or_404(
    listing_id: int,
    current_user: User,
    db: Session,
) -> Listing:
    listing = (
        db.query(Listing)
        # [중요] 단일 조회 시에도 연동 정보를 반드시 로딩해야 합니다.
        .options(selectinload(Listing.images))
        .options(selectinload(Listing.marketplace_links))
        .filter(
            Listing.id == listing_id,
            Listing.owner_id == current_user.id,
        )
        .first()
    )
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listing not found",
        )
    return listing


@router.get("/{listing_id}", response_model=ListingRead)
def get_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    return _attach_thumbnail(listing)


@router.put("/{listing_id}", response_model=ListingRead)
def update_listing(
    listing_id: int,
    listing_in: ListingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    
    # exclude_unset=True: 보내지 않은 필드는 건드리지 않음
    data = listing_in.model_dump(exclude_unset=True)
    
    for field, value in data.items():
        setattr(listing, field, value)

    db.add(listing)
    db.commit()
    db.refresh(listing)
    return _attach_thumbnail(listing)


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    db.delete(listing)
    db.commit()
    return None