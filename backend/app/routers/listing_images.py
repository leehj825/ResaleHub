import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.user import User

router = APIRouter(
    prefix="/listings",
    tags=["listing-images"],
)

settings = get_settings()


# ---------------------------
# 공통: Listing + 소유권 확인
# ---------------------------
def _get_owned_listing_or_404(listing_id: int, user: User, db: Session) -> Listing:
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Listing not found")

    if listing.owner_id != user.id:
        raise HTTPException(403, "Not authorized")

    return listing


# ---------------------------
# 이미지 업로드 (POST)
# ---------------------------
@router.post("/{listing_id}/images", status_code=status.HTTP_201_CREATED)
async def upload_listing_images(
    listing_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    # 저장 폴더: media/listings/<id>/
    listing_dir: Path = settings.media_root / "listings" / str(listing_id)
    listing_dir.mkdir(parents=True, exist_ok=True)

    # 기존 이미지 정렬번호 이어서 시작
    existing_count = (
        db.query(ListingImage).filter(ListingImage.listing_id == listing_id).count()
    )
    sort_order = existing_count

    uploaded_info: list[dict] = []

    for upload in files:
        filename = upload.filename or "image"
        ext = os.path.splitext(filename)[1].lower()

        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(400, f"Unsupported file type: {ext}")

        safe_name = f"{sort_order:03d}{ext}"
        file_path = listing_dir / safe_name

        # 파일 저장
        contents = await upload.read()
        file_path.write_bytes(contents)

        # DB에는 상대 경로: "listings/<id>/000.jpg"
        relative_path = Path("listings") / str(listing_id) / safe_name
        relative_path_str = str(relative_path)

        img = ListingImage(
            listing_id=listing_id,
            file_path=relative_path_str,
            sort_order=sort_order,
        )
        db.add(img)
        db.flush()  # id 확보용

        uploaded_info.append(
            {
                "id": img.id,
                "file_path": relative_path_str,
                "url": f"{settings.media_url}/{relative_path_str}",
            }
        )

        sort_order += 1

    # DB 반영
    db.commit()
    db.refresh(listing)

    # 썸네일 없으면 첫 이미지로 설정
    if listing.thumbnail_url is None and uploaded_info:
        listing.thumbnail_url = uploaded_info[0]["url"]
        db.add(listing)
        db.commit()
        db.refresh(listing)

    return {
        "listing_id": listing_id,
        "uploaded": uploaded_info,
    }


# ---------------------------
# 이미지 목록 조회 (GET)
#   → ["/media/listings/6/000.jpg", ...]
# ---------------------------
@router.get("/{listing_id}/images", response_model=List[str])
def list_listing_images(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_owned_listing_or_404(listing_id, current_user, db)

    images = (
        db.query(ListingImage)
        .filter(ListingImage.listing_id == listing_id)
        .order_by(ListingImage.sort_order.asc())
        .all()
    )

    return [f"{settings.media_url}/{img.file_path}" for img in images]


# ---------------------------
# 이미지 삭제 (DELETE)
#   filename 기반:
#   DELETE /listings/{id}/images/000.jpeg
# ---------------------------
@router.delete(
    "/{listing_id}/images/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_listing_image(
    listing_id: int,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    # DB file_path는 "listings/<id>/<filename>" 형태
    relative_path = Path("listings") / str(listing_id) / filename

    img = (
        db.query(ListingImage)
        .filter(
            ListingImage.listing_id == listing_id,
            ListingImage.file_path == str(relative_path),
        )
        .first()
    )

    if not img:
        raise HTTPException(404, "Image not found")

    # 실제 파일 삭제
    file_path = settings.media_root / img.file_path
    if file_path.exists():
        file_path.unlink()

    # DB 레코드 삭제
    db.delete(img)
    db.commit()

    # 남은 이미지들 sort_order 재정렬
    remaining = (
        db.query(ListingImage)
        .filter(ListingImage.listing_id == listing_id)
        .order_by(ListingImage.sort_order.asc())
        .all()
    )
    for idx, image in enumerate(remaining):
        image.sort_order = idx
        db.add(image)
    db.commit()

    # 썸네일 업데이트
    if remaining:
        listing.thumbnail_url = f"{settings.media_url}/{remaining[0].file_path}"
    else:
        listing.thumbnail_url = None

    db.add(listing)
    db.commit()

    return None
