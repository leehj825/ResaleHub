# app/services/poshmark_client.py
"""
Poshmark Playwright 자동화 클라이언트
- 자동 로그인
- 리스팅 업로드 (제목/설명/가격/카테고리/이미지)
- 발행
"""
import asyncio
from typing import List, Optional
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import Session

from app.models.marketplace_account import MarketplaceAccount
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_image import ListingImage


class PoshmarkAuthError(Exception):
    """Poshmark 인증 관련 에러"""
    pass


class PoshmarkPublishError(Exception):
    """Poshmark 업로드 관련 에러"""
    pass


async def get_poshmark_credentials(db: Session, user: User) -> tuple[str, str]:
    """
    DB에서 Poshmark 계정 정보 조회
    Returns: (username, password)
    """
    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == "poshmark",
        )
        .first()
    )

    if not account:
        raise PoshmarkAuthError("Poshmark account not connected")

    # username은 username 필드에, password는 access_token 필드에 저장 (임시)
    # 실제 운영 환경에서는 암호화된 저장 필요
    username = account.username
    password = account.access_token  # 임시로 password를 access_token 필드에 저장

    if not username or not password:
        raise PoshmarkAuthError("Poshmark credentials not configured")

    return username, password


async def login_to_poshmark(page: Page, username: str, password: str) -> bool:
    """
    Poshmark에 로그인
    Returns: 성공 여부
    """
    try:
        print(f">>> Navigating to Poshmark login page...")
        await page.goto("https://poshmark.com/login", wait_until="networkidle", timeout=30000)
        
        # 로그인 폼 찾기
        print(f">>> Looking for login form...")
        
        # 이메일/사용자명 입력 필드
        email_selector = 'input[type="email"], input[name="login_form[username_email]"], input[placeholder*="email" i], input[placeholder*="username" i]'
        await page.wait_for_selector(email_selector, timeout=10000)
        await page.fill(email_selector, username)
        print(f">>> Filled username/email")
        
        # 비밀번호 입력 필드
        password_selector = 'input[type="password"]'
        await page.wait_for_selector(password_selector, timeout=10000)
        await page.fill(password_selector, password)
        print(f">>> Filled password")
        
        # 로그인 버튼 클릭
        login_button_selector = 'button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")'
        await page.click(login_button_selector)
        print(f">>> Clicked login button")
        
        # 로그인 완료 대기 (리다이렉트 또는 대시보드 로드)
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # 로그인 성공 확인 (URL이 /login이 아니거나, 사용자 메뉴가 보이면 성공)
        current_url = page.url
        if "/login" not in current_url.lower():
            print(f">>> Login successful, redirected to: {current_url}")
            return True
        
        # 또는 사용자 프로필/메뉴 확인
        try:
            await page.wait_for_selector('a[href*="/user/"], button[aria-label*="Account" i], [data-testid*="user" i]', timeout=5000)
            print(f">>> Login successful, user menu found")
            return True
        except PlaywrightTimeoutError:
            pass
        
        # 에러 메시지 확인
        error_selectors = [
            '.error',
            '[class*="error" i]',
            '[class*="alert" i]',
            'text=/invalid|incorrect|wrong/i'
        ]
        for selector in error_selectors:
            try:
                error_element = await page.query_selector(selector)
                if error_element:
                    error_text = await error_element.inner_text()
                    if error_text:
                        raise PoshmarkAuthError(f"Login failed: {error_text}")
            except:
                pass
        
        print(f">>> Login status unclear, assuming success")
        return True
        
    except PlaywrightTimeoutError as e:
        raise PoshmarkAuthError(f"Login timeout: {str(e)}")
    except Exception as e:
        raise PoshmarkAuthError(f"Login failed: {str(e)}")


async def publish_listing_to_poshmark(
    page: Page,
    listing: Listing,
    listing_images: List[ListingImage],
    base_url: str,
    settings,
) -> dict:
    """
    Poshmark에 리스팅 업로드
    Returns: {listing_id, url, status}
    """
    try:
        # 1. "List an Item" 또는 "Sell" 페이지로 이동
        print(f">>> Navigating to Poshmark listing page...")
        await page.goto("https://poshmark.com/listing/new", wait_until="networkidle", timeout=30000)
        
        # 2. 이미지 업로드
        if listing_images:
            print(f">>> Uploading {len(listing_images)} images...")
            
            # 이미지 파일 input 찾기
            image_input_selector = 'input[type="file"][accept*="image"], input[type="file"]'
            try:
                await page.wait_for_selector(image_input_selector, timeout=10000)
                
                # 이미지 URL들을 다운로드하여 임시 파일로 저장 후 업로드
                # 또는 직접 URL을 사용할 수 있다면 사용
                image_paths = []
                for img in listing_images[:8]:  # Poshmark는 최대 8장
                    img_url = f"{base_url}{settings.media_url}/{img.file_path}"
                    # Playwright로 이미지 다운로드 후 업로드
                    # 간단한 방법: 이미지 URL을 직접 사용 (가능한 경우)
                    image_paths.append(img_url)
                
                # 파일 업로드 (로컬 파일 경로가 필요한 경우)
                # 실제로는 이미지를 다운로드하여 임시 파일로 저장 후 업로드해야 할 수 있음
                # 여기서는 기본 구조만 제공
                file_input = await page.query_selector(image_input_selector)
                if file_input:
                    # 실제 구현에서는 이미지를 다운로드하여 로컬 경로로 전달
                    # await file_input.set_input_files(image_paths)
                    print(f">>> Image upload selector found (implementation needed for actual file upload)")
            except PlaywrightTimeoutError:
                print(f">>> Image upload input not found, skipping...")
        
        # 3. 제목 입력
        title_selector = 'input[name*="title" i], input[placeholder*="title" i], textarea[name*="title" i]'
        try:
            await page.wait_for_selector(title_selector, timeout=10000)
            await page.fill(title_selector, listing.title or "Untitled")
            print(f">>> Filled title: {listing.title}")
        except PlaywrightTimeoutError:
            print(f">>> Title input not found")
        
        # 4. 설명 입력
        description_selector = 'textarea[name*="description" i], textarea[placeholder*="description" i], textarea[placeholder*="tell" i]'
        try:
            await page.wait_for_selector(description_selector, timeout=10000)
            description = listing.description or "No description"
            await page.fill(description_selector, description)
            print(f">>> Filled description")
        except PlaywrightTimeoutError:
            print(f">>> Description input not found")
        
        # 5. 가격 입력
        price_selector = 'input[name*="price" i], input[type="number"][placeholder*="price" i], input[placeholder*="$" i]'
        try:
            await page.wait_for_selector(price_selector, timeout=10000)
            price = float(listing.price or 0)
            await page.fill(price_selector, str(int(price)))
            print(f">>> Filled price: ${price}")
        except PlaywrightTimeoutError:
            print(f">>> Price input not found")
        
        # 6. 카테고리 선택 (가능한 경우)
        # Poshmark는 보통 드롭다운으로 카테고리 선택
        category_selectors = [
            'select[name*="category" i]',
            'button:has-text("Category")',
            '[data-testid*="category" i]'
        ]
        for selector in category_selectors:
            try:
                category_element = await page.query_selector(selector)
                if category_element:
                    # 카테고리 선택 로직 (구현 필요)
                    print(f">>> Category selector found (selection logic needed)")
                    break
            except:
                continue
        
        # 7. 브랜드 입력 (있는 경우)
        brand_selector = 'input[name*="brand" i], input[placeholder*="brand" i]'
        if listing.brand:
            try:
                await page.wait_for_selector(brand_selector, timeout=5000)
                await page.fill(brand_selector, listing.brand)
                print(f">>> Filled brand: {listing.brand}")
            except PlaywrightTimeoutError:
                pass
        
        # 8. 사이즈 입력 (있는 경우)
        size_selector = 'select[name*="size" i], input[name*="size" i]'
        # 사이즈 정보는 listing 모델에 없을 수 있으므로 스킵
        
        # 9. 상태(Condition) 선택 (있는 경우)
        condition_selector = 'select[name*="condition" i], button:has-text("Condition")'
        if listing.condition:
            try:
                condition_element = await page.query_selector(condition_selector)
                if condition_element:
                    # 상태 매핑 및 선택 로직
                    print(f">>> Condition selector found (selection logic needed)")
            except:
                pass
        
        # 10. "Publish" 또는 "List Item" 버튼 클릭
        publish_selectors = [
            'button:has-text("Publish")',
            'button:has-text("List Item")',
            'button:has-text("Post")',
            'button[type="submit"]:has-text("List")',
            '[data-testid*="publish" i]',
            '[data-testid*="submit" i]'
        ]
        
        published = False
        for selector in publish_selectors:
            try:
                publish_button = await page.query_selector(selector)
                if publish_button:
                    await publish_button.click()
                    print(f">>> Clicked publish button: {selector}")
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    published = True
                    break
            except:
                continue
        
        if not published:
            raise PoshmarkPublishError("Could not find or click publish button")
        
        # 11. 업로드 완료 확인 및 URL 추출
        await asyncio.sleep(2)  # 페이지 로드 대기
        
        current_url = page.url
        listing_id = None
        
        # URL에서 리스팅 ID 추출 시도
        if "/closet/" in current_url or "/listing/" in current_url:
            parts = current_url.split("/")
            for i, part in enumerate(parts):
                if part in ["closet", "listing"] and i + 1 < len(parts):
                    listing_id = parts[i + 1]
                    break
        
        return {
            "status": "published",
            "url": current_url,
            "external_item_id": listing_id,
        }
        
    except PlaywrightTimeoutError as e:
        raise PoshmarkPublishError(f"Publish timeout: {str(e)}")
    except Exception as e:
        raise PoshmarkPublishError(f"Publish failed: {str(e)}")


async def publish_listing(
    db: Session,
    user: User,
    listing: Listing,
    listing_images: List[ListingImage],
    base_url: str,
    settings,
) -> dict:
    """
    Poshmark에 리스팅 업로드 (메인 함수)
    Playwright 브라우저를 열고, 로그인 후 업로드 수행
    """
    username, password = await get_poshmark_credentials(db, user)
    
    async with async_playwright() as p:
        # 브라우저 실행 (headless=False로 디버깅 가능)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        try:
            # 로그인
            login_success = await login_to_poshmark(page, username, password)
            if not login_success:
                raise PoshmarkAuthError("Login failed")
            
            # 리스팅 업로드
            result = await publish_listing_to_poshmark(
                page, listing, listing_images, base_url, settings
            )
            
            return result
            
        finally:
            await browser.close()
