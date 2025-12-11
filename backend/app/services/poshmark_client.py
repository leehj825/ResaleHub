# app/services/poshmark_client.py
"""
Poshmark Playwright 자동화 클라이언트
- 자동 로그인 (세션 재사용 포함)
- 리스팅 업로드 (제목/설명/가격/카테고리/이미지)
- 발행
- 렌더(Render) 호스팅 최적화 적용
"""
import asyncio
import os
import tempfile
from typing import List, Optional
import httpx
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import Session

from app.models.marketplace_account import MarketplaceAccount
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_image import ListingImage
import json

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
    username = account.username
    password = account.access_token

    if not username or not password:
        raise PoshmarkAuthError("Poshmark credentials not configured")

    return username, password


async def block_resources(route):
    """
    불필요한 리소스 차단하여 속도 향상 (이미지, 폰트, 미디어)
    """
    if route.request.resource_type in ["image", "media", "font"]:
        await route.abort()
    else:
        await route.continue_()


def get_browser_launch_args():
    """
    Render/Cloud 환경을 위한 최적화된 브라우저 실행 인자
    """
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",  # 메모리 부족 방지
        "--disable-accelerated-2d-canvas",
        "--disable-gpu",            # GPU 없는 환경 최적화
        "--single-process",         # 리소스 절약 (선택사항)
    ]


async def verify_poshmark_credentials(username: str, password: str, headless: bool = True) -> bool:
    """
    Poshmark 자격 증명 검증 (연결 시 사용)
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=get_browser_launch_args()
            )
            
            # [FIX] User Agent를 Windows 10 Chrome으로 변경 (가장 일반적이고 안전함)
            # Render(Linux)에서 Mac User Agent를 쓰면 OS 불일치로 차단될 확률이 높음
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()
            
            # 리소스 차단 (속도)
            await page.route("**/*", block_resources)
            
            try:
                print(f">>> Starting quick login verification...")
                login_success = await login_to_poshmark_quick(page, username, password)
                return login_success
            finally:
                await browser.close()
    except Exception as e:
        print(f">>> Credential verification error: {e}")
        return False


async def login_to_poshmark_quick(page: Page, username: str, password: str) -> bool:
    """
    Verification Login with Debugging
    """
    try:
        print(f">>> Navigating to Poshmark login page...")
        
        # Go to Login URL
        await page.goto("https://poshmark.com/login", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2) # Wait for redirects/challenges
        
        # [DEBUG] Print the Page Title to know where we are
        page_title = await page.title()
        print(f">>> Current Page Title: '{page_title}'")
        
        # [Check 1] Cloudflare / Security Check
        if "Just a moment" in page_title or "Security" in page_title or "Challenge" in page_title:
             print(">>> Blocked by Cloudflare Security Challenge.")
             await page.screenshot(path="/tmp/blocked_cloudflare.png")
             raise PoshmarkAuthError("Bot blocked by Cloudflare (Just a moment...)")

        # [Check 2] "Pardon the interruption"
        if await page.query_selector("text=Pardon the interruption"):
            print(">>> Blocked by 'Pardon the interruption'.")
            raise PoshmarkAuthError("Bot detected: 'Pardon the interruption'")

        # [Check 3] Find Email Field
        email_selectors = [
            'input[name="login_form[username_email]"]',
            'input[name*="email" i]', 
            'input[name*="username" i]',
        ]
        
        email_field = None
        for selector in email_selectors:
            try:
                email_field = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if email_field: break
            except: continue

        # [Check 4] If missing, try clicking "Log in" (Homepage Redirect Case)
        if not email_field:
            print(">>> Email field missing. Checking for 'Log In' button...")
            try:
                # Look for header login button
                login_btn = await page.wait_for_selector(
                    'header a[href="/login"], a:has-text("Log in"), button:has-text("Log in")', 
                    timeout=3000
                )
                if login_btn:
                    print(">>> Found Log In button, clicking...")
                    await login_btn.click()
                    await asyncio.sleep(2)
                    
                    # Try finding email again
                    email_field = await page.wait_for_selector('input[name*="username_email"]', timeout=5000)
            except:
                pass

        if not email_field:
            # [DEBUG] Log the HTML snippet to see what text is actually on the page
            content_snippet = await page.content()
            print(f">>> Page HTML Snippet (First 500 chars): {content_snippet[:500]}")
            
            await page.screenshot(path="/tmp/quick_login_fail.png")
            raise PoshmarkAuthError(f"Login form not found. Title: '{page_title}'. See /tmp/quick_login_fail.png")
        
        # Proceed with Login
        await email_field.fill(username)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"]')
        
        # Wait for result
        try:
            await page.wait_for_url(lambda u: "/login" not in u.lower(), timeout=10000)
        except: pass
        
        if "/login" not in page.url.lower():
            return True
            
        return False
        
    except Exception as e:
        print(f">>> Quick login failed: {e}")
        raise PoshmarkAuthError(f"Login verification failed: {str(e)}")


async def login_to_poshmark(page: Page, username: str, password: str) -> bool:
    """
    Poshmark에 로그인 (일반)
    """
    try:
        print(f">>> Navigating to Poshmark login page...")
        await page.goto("https://poshmark.com/login", wait_until="domcontentloaded", timeout=60000)
        
        # 로그인 폼 찾기
        try:
            email_field = await page.wait_for_selector(
                'input[name="login_form[username_email]"], input[name*="username" i], input[type="email"]', 
                timeout=10000, 
                state="visible"
            )
            await email_field.fill(username)
        except PlaywrightTimeoutError:
             # 봇 탐지 페이지 확인
            if await page.query_selector("text=Pardon the interruption"):
                 raise PoshmarkAuthError("Bot detected by Poshmark (CAPTCHA/Security Screen).")
            
            await page.screenshot(path="/tmp/login_fail.png")
            raise PoshmarkAuthError("Could not find login form. See /tmp/login_fail.png")

        password_field = await page.wait_for_selector('input[type="password"]', state="visible")
        await password_field.fill(password)
        
        login_btn = await page.wait_for_selector('button[type="submit"]', state="visible")
        await login_btn.click()
        
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        if "/login" not in page.url.lower():
            print(f">>> Login successful, redirected to: {page.url}")
            return True
            
        # 로그인 실패 메시지 확인
        error_el = await page.query_selector(".error_message, .error")
        if error_el:
            text = await error_el.inner_text()
            raise PoshmarkAuthError(f"Login refused: {text}")

        return True
        
    except Exception as e:
        raise PoshmarkAuthError(f"Login process failed: {str(e)}")


async def publish_listing_to_poshmark(
    page: Page,
    listing: Listing,
    listing_images: List[ListingImage],
    base_url: str,
    settings,
) -> dict:
    """
    Poshmark에 리스팅 업로드
    """
    try:
        print(f">>> Navigating to Poshmark listing page...")
        listing_url = "https://poshmark.com/listing/new"
        
        try:
            await page.goto(listing_url, wait_until="load", timeout=30000)
            
            # [CRITICAL FIX] 폼 요소가 없으면 실패 처리 (Blind Bot 방지)
            try:
                await page.wait_for_selector(
                    'input[type="file"], input[name*="title" i]',
                    timeout=15000,
                    state="attached"
                )
            except PlaywrightTimeoutError:
                # 봇 탐지 화면인지 확인
                if await page.query_selector("text=Pardon the interruption"):
                    raise PoshmarkPublishError("Bot detected: 'Pardon the interruption' screen active.")
                
                # 스크린샷 저장
                screenshot_path = "/tmp/debug_failed_form_load.png"
                await page.screenshot(path=screenshot_path)
                print(f">>> Failed to load form. Screenshot saved to {screenshot_path}")
                
                # 페이지 소스 일부 로깅
                content = await page.content()
                print(f">>> Page content sample: {content[:500]}")
                
                raise PoshmarkPublishError("Could not find listing form elements. Likely blocked or page layout changed.")
                
        except Exception as e:
            if isinstance(e, PoshmarkPublishError):
                raise
            raise PoshmarkPublishError(f"Could not access Poshmark listing page: {str(e)}")
        
        # 2. 이미지 업로드 (리소스 차단을 피하기 위해 이 부분은 주의 필요)
        if listing_images:
            print(f">>> Uploading {len(listing_images)} images...")
            image_input_selector = 'input[type="file"]'
            
            try:
                file_input = await page.wait_for_selector(image_input_selector, timeout=5000, state="attached")
                
                if file_input:
                    # 이미지 다운로드 및 임시 파일 생성
                    print(f">>> Downloading {len(listing_images[:8])} images...")
                    
                    async def download_image(img: ListingImage) -> Optional[str]:
                        try:
                            img_url = f"{base_url}{settings.media_url}/{img.file_path}"
                            async with httpx.AsyncClient() as client:
                                response = await client.get(img_url, timeout=15.0)
                                if response.status_code == 200:
                                    suffix = os.path.splitext(img.file_path)[1] or '.jpg'
                                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                                    temp_file.write(response.content)
                                    temp_file.close()
                                    return temp_file.name
                        except Exception as e:
                            print(f">>> Failed to download {img.file_path}: {e}")
                            return None
                    
                    download_tasks = [download_image(img) for img in listing_images[:8]]
                    temp_files = [f for f in await asyncio.gather(*download_tasks) if f]
                    
                    if temp_files:
                        try:
                            await file_input.set_input_files(temp_files)
                            print(f">>> Uploaded {len(temp_files)} images")
                            await asyncio.sleep(2) # 업로드 처리 대기
                        finally:
                            for temp_file in temp_files:
                                try:
                                    os.unlink(temp_file)
                                except:
                                    pass
            except Exception as e:
                print(f">>> Warning: Image upload failed: {e}")
        
        # 3. 필수 필드 입력
        print(f">>> Filling listing details...")
        
        # 제목
        await page.fill('input[name*="title" i], input[placeholder*="title" i]', listing.title or "Untitled")
        
        # 설명
        await page.fill('textarea[name*="description" i]', listing.description or "No description")
        
        # 가격
        price = str(int(float(listing.price or 0)))
        await page.fill('input[name*="price" i], input[placeholder*="Original Price"]', price) # Original Price
        await page.fill('input[name="current_price"], input[data-testid="price-input"]', price) # Listing Price
        
        # 4. 발행 버튼 클릭
        print(f">>> Looking for publish button...")
        
        publish_btn = await page.wait_for_selector(
            'button[type="submit"]:has-text("List Item"), button:has-text("Next"), button:has-text("Publish")',
            state="visible", 
            timeout=5000
        )
        
        if not publish_btn:
            await page.screenshot(path="/tmp/no_publish_btn.png")
            raise PoshmarkPublishError("Publish button not found")

        await publish_btn.click()
        print(">>> Clicked publish button")
        
        # 완료 대기
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except:
            pass

        current_url = page.url
        listing_id = None
        if "/listing/" in current_url:
             parts = current_url.split("/")
             listing_id = parts[-1].split("-")[-1] # URL 구조에 따라 다름

        return {
            "status": "published",
            "url": current_url,
            "external_item_id": listing_id,
        }
        
    except Exception as e:
        # 에러 발생 시 스크린샷 캡처
        try:
            await page.screenshot(path="/tmp/publish_error.png")
        except:
            pass
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
    - 최적화된 브라우저 실행
    - 세션(쿠키) 재사용 적용
    """
    username, password = await get_poshmark_credentials(db, user)
    
    # 세션 파일 경로 설정 (유저별 분리)
    session_file_path = f"/tmp/poshmark_session_{user.id}.json"
    
    try:
        async with async_playwright() as p:
            # 1. 브라우저 실행 (Render 최적화 인자 적용)
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=get_browser_launch_args()
                )
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    raise PoshmarkPublishError(
                        "Playwright browser not installed. Check build command."
                    )
                raise
            
            # 2. 세션 로드 시도 또는 새 컨텍스트 생성
            context = None
            if os.path.exists(session_file_path):
                try:
                    context = await browser.new_context(
                        storage_state=session_file_path,
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                    )
                    print(f">>> Loaded existing session for user {user.id}")
                except Exception as e:
                    print(f">>> Failed to load session: {e}")
            
            if not context:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                )
            
            page = await context.new_page()
            
            # 3. 리소스 차단 적용 (속도 향상)
            # 이미지 업로드에 필요한 리소스는 제외하고 차단할 수도 있으나,
            # Playwright의 file input 조작은 네트워크 요청 없이 작동하므로 일반적으로 안전함.
            # 단, Poshmark의 미리보기 생성 스크립트가 중요할 수 있으므로 'image'만 차단.
            await page.route("**/*", block_resources)
            
            try:
                # 4. 로그인 상태 확인 및 로그인
                is_logged_in = False
                
                # 메인 피드나 뉴스 페이지로 이동하여 로그인 여부 확인
                try:
                    await page.goto("https://poshmark.com/feed", timeout=10000, wait_until="domcontentloaded")
                    # URL에 login이 없고, 유저 아이콘이나 메뉴가 보이면 로그인 된 것임
                    if "login" not in page.url and await page.query_selector('.header-user-profile, a[href*="/user/"]'):
                        is_logged_in = True
                        print(">>> Session is valid, skipping login.")
                except:
                    pass
                
                if not is_logged_in:
                    print(">>> Session invalid or missing, logging in...")
                    login_success = await login_to_poshmark(page, username, password)
                    if not login_success:
                        raise PoshmarkAuthError("Login failed")
                    
                    # 로그인 성공 시 세션 저장
                    await context.storage_state(path=session_file_path)
                    print(f">>> Saved new session to {session_file_path}")
                
                # 5. 리스팅 업로드 수행
                result = await publish_listing_to_poshmark(
                    page, listing, listing_images, base_url, settings
                )
                
                return result
                
            finally:
                try:
                    await browser.close()
                except:
                    pass
    except PoshmarkPublishError:
        raise
    except Exception as e:
        raise PoshmarkPublishError(f"System error: {str(e)}")


async def get_poshmark_inventory(db: Session, user: User) -> List[dict]:
    """
    Poshmark 인벤토리 조회
    """
    username, password = await get_poshmark_credentials(db, user)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=get_browser_launch_args()
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            # 리소스 차단 (인벤토리 조회는 텍스트만 필요하므로 강력하게 적용)
            await page.route("**/*", block_resources)
            
            try:
                login_success = await login_to_poshmark_quick(page, username, password)
                if not login_success:
                    raise PoshmarkAuthError("Login failed")
                
                print(f">>> Navigating to closet page...")
                closet_url = f"https://poshmark.com/closet/{username}"
                await page.goto(closet_url, wait_until="load", timeout=20000)
                
                print(f">>> Extracting listings from closet...")
                items = await page.evaluate("""
                    () => {
                        const items = [];
                        const cards = document.querySelectorAll('.tile, .listing-tile, [class*="tile"]');
                        cards.forEach((card, index) => {
                            try {
                                const titleEl = card.querySelector('a[href*="/listing/"], .title');
                                const title = titleEl ? titleEl.innerText.trim() : `Item ${index}`;
                                const priceEl = card.querySelector('.price, .amount');
                                const price = priceEl ? parseFloat(priceEl.innerText.replace(/[^0-9.]/g, '')) : 0;
                                const linkEl = card.querySelector('a[href*="/listing/"]');
                                const url = linkEl ? linkEl.href : '';
                                
                                if (title && url) {
                                    items.push({ title, price, url, sku: `poshmark-${index}` });
                                }
                            } catch (e) {}
                        });
                        return items;
                    }
                """)
                
                print(f">>> Found {len(items)} items")
                return items
                
            finally:
                await browser.close()
    except Exception as e:
        raise PoshmarkPublishError(f"Failed to fetch inventory: {str(e)}")
    

# Updated function to use cookies
async def verify_poshmark_credentials(username: str, cookie_json: str, headless: bool = True) -> bool:
    """
    Verify credentials using SAVED COOKIES (No password typing).
    """
    try:
        cookies = json.loads(cookie_json) # Parse the JSON string from DB
    except:
        print(">>> Error: Stored credentials are not valid JSON cookies.")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=get_browser_launch_args())
        
        # Create context and LOAD COOKIES immediately
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...", # Match your real UA
        )
        await context.add_cookies(cookies) # <--- MAGIC HAPPENS HERE
        
        page = await context.new_page()
        
        # Now just go to the feed. If cookies work, we are logged in!
        print(">>> Navigating to Feed with cookies...")
        await page.goto("https://poshmark.com/feed", timeout=20000)
        
        # Check if we are logged in
        if "login" not in page.url and await page.query_selector('.header-user-profile, a[href*="/user/"]'):
             print(">>> Cookie Login Successful!")
             return True
        else:
             print(">>> Cookie Login Failed (Expired?)")
             return False