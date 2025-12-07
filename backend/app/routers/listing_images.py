import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.user import User

router = APIRouter(
    prefix="/listings",
    tags=["listings-images"],
)

settings = Settings()


@router.post("/{listing_id}/images", status_code=status.HTTP_201_CREATED)
async def upload_listing_images(
    listing_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) Listing 존재 여부 + 소유권 확인
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if listing.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this listing")

    # 2) 저장 폴더: media/listings/<listing_id>/
    listing_dir: Path = settings.media_root / "listings" / str(listing_id)
    listing_dir.mkdir(parents=True, exist_ok=True)

    # 기존 이미지 개수 확인해서 sort_order 이어 붙이기
    existing_count = (
        db.query(ListingImage)
        .filter(ListingImage.listing_id == listing_id)
        .count()
    )
    sort_order = existing_count

    created_images = []

    for upload in files:
        # 간단한 확장자 체크 (선택 사항)
        filename = upload.filename or "image"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

        # 파일명 유니크하게 (sort_order + 원본 이름)
        safe_name = f"{sort_order:03d}{ext}"
        file_path = listing_dir / safe_name

        # 파일 저장
        contents = await upload.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # DB에 레코드 추가 (상대경로 저장: "listings/1/000.jpg" 형태)
        relative_path = Path("listings") / str(listing_id) / safe_name

        img = ListingImage(
            listing_id=listing_id,
            file_path=str(relative_path),
            sort_order=sort_order,
        )
        db.add(img)
        created_images.append(img)

        sort_order += 1

    db.commit()

    # 간단 응답
    return {
        "listing_id": listing_id,
        "uploaded": [
            {
                "id": img.id,
                "file_path": img.file_path,
                "url": f"{settings.media_url}/{img.file_path}",
            }
            for img in created_images
        ],
    }
