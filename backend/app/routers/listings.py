from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload 

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import Settings
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_marketplace import ListingMarketplace # [Added] Needed for saving connection info
from app.schemas.listing import ListingCreate, ListingRead, ListingUpdate

router = APIRouter(prefix="/listings", tags=["listings"])

settings = Settings()


def _attach_thumbnail(listing: Listing) -> ListingRead:
    """
    Helper function to attach a thumbnail URL when converting 
    a SQLAlchemy Listing object to ListingRead.
    """
    # When model_validate is called, pre-loaded marketplace_links are also converted.
    data = ListingRead.model_validate(listing)

    # Use the first image in the Listing.images relationship as the thumbnail
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
        # [Important] Eager load images and marketplace links together
        .options(selectinload(Listing.images))
        .options(selectinload(Listing.marketplace_links))
        .order_by(Listing.created_at.desc())
        .all()
    )

    # Convert to list of ListingRead with thumbnails attached
    return [_attach_thumbnail(l) for l in listings]


@router.post("/", response_model=ListingRead, status_code=status.HTTP_201_CREATED)
def create_listing(
    listing_in: ListingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Separate fields not in the DB model (used for import logic)
    listing_data = listing_in.model_dump(exclude={
        "import_from_marketplace", 
        "import_external_id", 
        "import_url"
    })
    
    # 2. Create Listing (includes sku, condition)
    listing = Listing(
        **listing_data,
        owner_id=current_user.id
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    # 3. [Import Logic] Automatically create connection info if imported from eBay
    if listing_in.import_from_marketplace:
        marketplace = listing_in.import_from_marketplace
        
        # Check for duplicates just in case
        existing_link = db.query(ListingMarketplace).filter(
            ListingMarketplace.listing_id == listing.id,
            ListingMarketplace.marketplace == marketplace
        ).first()

        if not existing_link:
            new_link = ListingMarketplace(
                listing_id=listing.id,
                marketplace=marketplace,
                status="published", # Imported items are already published
                external_item_id=listing_in.import_external_id,
                external_url=listing_in.import_url,
                sku=listing.sku,    # Use the SKU saved in the Listing
                offer_id=None       # Offer ID is unknown during inventory import, so leave blank
            )
            db.add(new_link)
            db.commit()
            
            # Reload listing to include the new connection info
            db.refresh(listing)

    return _attach_thumbnail(listing)


def _get_owned_listing_or_404(
    listing_id: int,
    current_user: User,
    db: Session,
) -> Listing:
    listing = (
        db.query(Listing)
        # [Important] Must eager load connection info even for single item retrieval
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
    
    # exclude_unset=True: Do not touch fields that were not sent
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