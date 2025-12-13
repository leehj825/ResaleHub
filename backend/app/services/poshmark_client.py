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
import json
import logging
from typing import List, Optional
import httpx
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import Session

from app.models.marketplace_account import MarketplaceAccount
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_image import ListingImage

class PoshmarkAuthError(Exception):
    """Poshmark 인증 관련 에러"""
    def __init__(self, message: str, screenshot_base64: str = None):
        super().__init__(message)
        self.screenshot_base64 = screenshot_base64


class PoshmarkPublishError(Exception):
    """Poshmark 업로드 관련 에러"""
    pass


async def get_poshmark_credentials(db: Session, user: User) -> tuple[str, str]:
    """
    DB에서 Poshmark 계정 정보 조회
    Returns: (username, password)
    DEPRECATED: Use get_poshmark_cookies instead for cookie-based auth
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


async def get_poshmark_cookies(db: Session, user: User) -> tuple[str, list]:
    """
    DB에서 Poshmark 쿠키 정보 조회
    Returns: (username, cookies_list)
    """
    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == "poshmark",
        )
        .first()
    )

    if not account or not account.access_token:
        raise PoshmarkAuthError("Poshmark account not connected")

    # access_token 필드에 JSON 형태로 쿠키가 저장되어 있음
    try:
        cookies = json.loads(account.access_token)
        if not isinstance(cookies, list):
            raise PoshmarkAuthError("Invalid cookie format in database")
        
        username = account.username or "Connected Account"
        return username, cookies
    except json.JSONDecodeError:
        raise PoshmarkAuthError("Failed to parse cookies from database")


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
    - 쿠키 기반 인증 사용
    - 최적화된 브라우저 실행
    """
    import sys
    import time
    start_time = time.time()
    
    def log(msg):
        """Log with timestamp and flush immediately"""
        elapsed = time.time() - start_time
        print(f">>> [PUBLISH {elapsed:.1f}s] {msg}", flush=True)
        sys.stdout.flush()
    
    log("Starting Poshmark listing publish...")
    username, cookies = await get_poshmark_cookies(db, user)
    log(f"Retrieved cookies for user: {username} ({len(cookies)} cookies)")
    
    try:
        log("Initializing Playwright browser...")
        async with async_playwright() as p:
            # 1. 브라우저 실행
            try:
                log("Launching Chromium browser...")
                browser = await p.chromium.launch(
                    headless=True,
                    args=get_browser_launch_args()
                )
                log("Browser launched")
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    raise PoshmarkPublishError(
                        "Playwright browser not installed. Check build command."
                    )
                raise
            
            # 2. Create context and load cookies
            log("Creating browser context...")
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            # Navigate to domain first before adding cookies
            log("Navigating to poshmark.com to set cookie domain...")
            page_temp = await context.new_page()
            try:
                await page_temp.goto("https://poshmark.com", wait_until="domcontentloaded", timeout=10000)
            except:
                pass
            await page_temp.close()
            
            # Load cookies
            log("Loading cookies into browser context...")
            import time as time_module
            current_timestamp = time_module.time()
            
            playwright_cookies = []
            for cookie in cookies:
                # Skip expired cookies
                if cookie.get("expirationDate"):
                    expiration = cookie.get("expirationDate")
                    if isinstance(expiration, (int, float)) and expiration < current_timestamp:
                        continue
                
                # Extract domain
                domain = cookie.get("domain", "poshmark.com")
                if domain.startswith("."):
                    domain = domain[1:]
                if not domain or "poshmark.com" not in domain:
                    domain = "poshmark.com"
                
                # Skip invalid cookies
                name = cookie.get("name", "").strip()
                value = cookie.get("value", "").strip()
                if not name or not value:
                    continue
                
                playwright_cookie = {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": cookie.get("path", "/"),
                }
                
                if cookie.get("secure"):
                    playwright_cookie["secure"] = True
                if cookie.get("httpOnly"):
                    playwright_cookie["httpOnly"] = True
                if cookie.get("expirationDate"):
                    exp_date = cookie.get("expirationDate")
                    if isinstance(exp_date, (int, float)) and exp_date > current_timestamp:
                        playwright_cookie["expires"] = int(exp_date)
                
                # Handle sameSite
                same_site = cookie.get("sameSite")
                if same_site:
                    same_site_str = str(same_site).strip().upper()
                    if same_site_str == "STRICT":
                        playwright_cookie["sameSite"] = "Strict"
                    elif same_site_str == "LAX":
                        playwright_cookie["sameSite"] = "Lax"
                    elif same_site_str in ["NONE", "NO_RESTRICTION", "UNSPECIFIED"]:
                        playwright_cookie["sameSite"] = "None"
                
                playwright_cookies.append(playwright_cookie)
            
            # Final safety check: Remove invalid sameSite values
            valid_same_site_values = {"Strict", "Lax", "None"}
            for cookie in playwright_cookies:
                if "sameSite" in cookie and cookie["sameSite"] not in valid_same_site_values:
                    del cookie["sameSite"]
            
            await context.add_cookies(playwright_cookies)
            log(f"Loaded {len(playwright_cookies)} cookies into browser context")
            
            page = await context.new_page()
            
            # 3. 리소스 차단 적용 (이미지만 차단, 스크립트는 허용)
            async def selective_block(route):
                resource_type = route.request.resource_type
                if resource_type in ["image", "font", "media"]:
                    await route.abort()
                else:
                    await route.continue_()
            
            await page.route("**/*", selective_block)
            log("Resource blocking configured")
            
            try:
                # 4. 로그인 상태 확인
                log("Checking login status...")
                await page.goto("https://poshmark.com/feed", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1)  # Wait for dynamic content
                
                is_logged_in = False
                page_url = page.url.lower()
                
                if "login" not in page_url and "sign-in" not in page_url:
                    user_profile = await page.query_selector('.header-user-profile, a[href*="/user/"], a[href*="/closet/"]')
                    if user_profile:
                        is_logged_in = True
                        log("✓ Cookie authentication successful")
                
                if not is_logged_in:
                    log("✗ Cookie authentication failed")
                    screenshot_base64 = None
                    try:
                        screenshot_bytes = await page.screenshot(full_page=True)
                        import base64
                        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                    except Exception:
                        pass
                    raise PoshmarkAuthError(
                        "Cookies are invalid or expired. Please reconnect your Poshmark account using the Chrome Extension.",
                        screenshot_base64=screenshot_base64
                    )
                
                # 5. 리스팅 업로드 수행
                log("Starting listing upload...")
                result = await publish_listing_to_poshmark(
                    page, listing, listing_images, base_url, settings
                )
                
                log(f"✓ Publish successful! Total time: {time.time() - start_time:.1f}s")
                return result
                
            finally:
                log("Closing browser...")
                try:
                    await browser.close()
                except:
                    pass
    except PoshmarkAuthError:
        log(f"✗ Authentication error after {time.time() - start_time:.1f}s")
        raise
    except PoshmarkPublishError:
        log(f"✗ Publish error after {time.time() - start_time:.1f}s")
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        log(f"✗ System error after {time.time() - start_time:.1f}s: {error_details}")
        raise PoshmarkPublishError(f"System error: {str(e)}")


async def get_poshmark_inventory(db: Session, user: User) -> List[dict]:
    """
    Poshmark 인벤토리 조회 (쿠키 기반 인증 사용)
    """
    import sys
    import time
    start_time = time.time()
    
    def log(msg):
        """Log with timestamp and flush immediately"""
        elapsed = time.time() - start_time
        print(f">>> [{elapsed:.1f}s] {msg}", flush=True)
        sys.stdout.flush()
    
    log("Starting Poshmark inventory fetch...")
    username, cookies = await get_poshmark_cookies(db, user)
    log(f"Retrieved cookies for user: {username} ({len(cookies)} cookies)")
    
    try:
        log("Initializing Playwright browser...")
        async with async_playwright() as p:
            log("Launching Chromium browser...")
            browser = await p.chromium.launch(
                headless=True,
                args=get_browser_launch_args()
            )
            log("Browser launched, creating context...")
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            log("Browser context created")
            
            # 쿠키를 컨텍스트에 추가
            log("Processing cookies...")
            try:
                import time
                current_timestamp = time.time()
                
                # Playwright cookie format에 맞게 변환
                playwright_cookies = []
                expired_count = 0
                invalid_count = 0
                
                for cookie in cookies:
                    # Skip expired cookies
                    if cookie.get("expirationDate"):
                        expiration = cookie.get("expirationDate")
                        if isinstance(expiration, (int, float)):
                            if expiration < current_timestamp:
                                expired_count += 1
                                continue
                    
                    # Extract domain - handle both .poshmark.com and poshmark.com
                    domain = cookie.get("domain", "poshmark.com")
                    if domain.startswith("."):
                        domain = domain[1:]  # Remove leading dot for Playwright
                    
                    # Ensure domain is valid
                    if not domain or "poshmark.com" not in domain:
                        domain = "poshmark.com"
                    
                    # Skip cookies without name or value
                    name = cookie.get("name", "").strip()
                    value = cookie.get("value", "").strip()
                    if not name or not value:
                        invalid_count += 1
                        continue
                    
                    playwright_cookie = {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": cookie.get("path", "/"),
                    }
                    
                    # Optional fields
                    if cookie.get("secure"):
                        playwright_cookie["secure"] = True
                    if cookie.get("httpOnly"):
                        playwright_cookie["httpOnly"] = True
                    if cookie.get("expirationDate"):
                        exp_date = cookie.get("expirationDate")
                        if isinstance(exp_date, (int, float)) and exp_date > current_timestamp:
                            playwright_cookie["expires"] = int(exp_date)
                    
                    # Handle sameSite (Playwright expects exactly "Strict", "Lax", or "None")
                    # Chrome can return: "Strict", "Lax", "None", "No_Restriction", "Unspecified", or undefined
                    # IMPORTANT: Only include sameSite if it's a valid value, otherwise omit it completely
                    same_site = cookie.get("sameSite")
                    
                    # Only process sameSite if it exists and is not None/empty
                    if same_site is not None:
                        same_site_str = str(same_site).strip()
                        if same_site_str:  # Only process non-empty strings
                            same_site_upper = same_site_str.upper()
                            
                            # Map Chrome values to Playwright values (must be exact: "Strict", "Lax", or "None")
                            if same_site_upper == "STRICT":
                                playwright_cookie["sameSite"] = "Strict"
                            elif same_site_upper == "LAX":
                                playwright_cookie["sameSite"] = "Lax"
                            elif same_site_upper in ["NONE", "NO_RESTRICTION", "UNSPECIFIED"]:
                                playwright_cookie["sameSite"] = "None"
                            else:
                                # If it's an invalid value, don't include sameSite (Playwright will use default)
                                print(f">>> Warning: Unknown sameSite value '{same_site}' (type: {type(same_site)}) for cookie '{name}', omitting")
                        # If same_site is empty string or whitespace, don't include it
                    
                    # Note: We intentionally don't add sameSite if it's invalid/empty
                    # Playwright will use its default behavior
                    
                    playwright_cookies.append(playwright_cookie)
                
                if expired_count > 0:
                    print(f">>> Warning: {expired_count} expired cookies were skipped")
                if invalid_count > 0:
                    print(f">>> Warning: {invalid_count} invalid cookies were skipped")
                
                if len(playwright_cookies) == 0:
                    raise PoshmarkAuthError("No valid cookies found. All cookies may be expired. Please reconnect your Poshmark account.")
                
                # Final safety check: Remove any invalid sameSite values
                valid_same_site_values = {"Strict", "Lax", "None"}
                for cookie in playwright_cookies:
                    if "sameSite" in cookie:
                        same_site_val = cookie["sameSite"]
                        if same_site_val not in valid_same_site_values:
                            print(f">>> WARNING: Removing invalid sameSite value '{same_site_val}' from cookie '{cookie.get('name')}'")
                            del cookie["sameSite"]
                
                # Debug: Log first cookie's sameSite value before adding
                if len(playwright_cookies) > 0:
                    first_cookie = playwright_cookies[0]
                    if "sameSite" in first_cookie:
                        print(f">>> DEBUG: First cookie '{first_cookie.get('name')}' has sameSite='{first_cookie.get('sameSite')}'")
                    else:
                        print(f">>> DEBUG: First cookie '{first_cookie.get('name')}' has no sameSite field")
                
                # Navigate to domain first before adding cookies (required by Playwright)
                page_temp = await context.new_page()
                try:
                    await page_temp.goto("https://poshmark.com", wait_until="domcontentloaded", timeout=10000)
                except:
                    pass  # Continue even if navigation fails
                await page_temp.close()
                
                # Add cookies to context
                await context.add_cookies(playwright_cookies)
                print(f">>> Loaded {len(playwright_cookies)} valid cookies into browser context")
                
            except PoshmarkAuthError:
                raise
            except Exception as e:
                print(f">>> Error loading cookies: {e}")
                import traceback
                traceback.print_exc()
                raise PoshmarkAuthError(f"Failed to load cookies: {str(e)}")
            
            log("Creating new page...")
            page = await context.new_page()
            
            # 리소스 차단 (인벤토리 조회는 텍스트만 필요하므로 강력하게 적용)
            # 단, 스크립트는 허용 (동적 콘텐츠 로딩에 필요)
            log("Setting up resource blocking...")
            async def selective_block(route):
                resource_type = route.request.resource_type
                if resource_type in ["image", "font", "media"]:
                    await route.abort()
                else:
                    await route.continue_()
            
            await page.route("**/*", selective_block)
            log("Resource blocking configured")
            
            try:
                # 로그인 상태 확인
                log("Navigating to feed page to check login status...")
                await page.goto("https://poshmark.com/feed", wait_until="domcontentloaded", timeout=20000)
                log(f"Feed page loaded: {page.url}")
                
                # Wait a bit for dynamic content to load
                await asyncio.sleep(2)
                
                # 로그인 여부 확인 - try multiple methods
                log("Checking login status...")
                is_logged_in = False
                page_url = page.url.lower()
                log(f"Current URL: {page.url}")
                
                # Method 1: Check if URL contains login/sign-in (definitely not logged in)
                if "login" in page_url or "sign-in" in page_url or "signin" in page_url:
                    print(">>> URL indicates login page - not authenticated")
                    is_logged_in = False
                else:
                    # Method 2: Check for user profile elements
                    user_profile_selectors = [
                        '.header-user-profile',
                        'a[href*="/user/"]',
                        '[data-testid*="user"]',
                        '.user-profile',
                        'a[href*="/closet/"]',
                        'nav a[href*="/user/"]',
                    ]
                    
                    for selector in user_profile_selectors:
                        try:
                            element = await page.query_selector(selector)
                            if element:
                                log(f"Found user profile element with selector: {selector}")
                                is_logged_in = True
                                
                                # Try to extract username from this element
                                if selector == 'a[href*="/closet/"]':
                                    href = await element.get_attribute("href")
                                    if href:
                                        import re
                                        match = re.search(r"/closet/([A-Za-z0-9_\-]+)", href)
                                        if match:
                                            username = match.group(1)
                                            log(f"Extracted username from closet link: {username}")
                                elif selector == 'a[href*="/user/"]':
                                    href = await element.get_attribute("href")
                                    if href:
                                        import re
                                        match = re.search(r"/user/([A-Za-z0-9_\-]+)", href)
                                        if match:
                                            username = match.group(1)
                                            log(f"Extracted username from user link: {username}")
                                break
                        except:
                            continue
                    
                    # Method 3: Check page content for logged-in indicators
                    if not is_logged_in:
                        try:
                            page_content = await page.content()
                            logged_in_indicators = [
                                "Sign Out",
                                "Log Out",
                                "Sign out",
                                "My Closet",
                                "My Poshmark",
                            ]
                            for indicator in logged_in_indicators:
                                if indicator in page_content:
                                    print(f">>> Found logged-in indicator in content: {indicator}")
                                    is_logged_in = True
                                    break
                        except Exception as e:
                            print(f">>> Could not check page content: {e}")
                
                if is_logged_in:
                    log("✓ Cookie authentication successful")
                else:
                    log("✗ Cookie authentication failed - no logged-in indicators found")
                
                if not is_logged_in:
                    # Try to get more details about why login failed
                    page_url = page.url.lower()
                    if "login" in page_url or "sign-in" in page_url:
                        raise PoshmarkAuthError("Cookies are invalid or expired. Please reconnect your Poshmark account using the Chrome Extension.")
                    else:
                        # Check if there's a specific error message on the page
                        try:
                            error_selectors = [
                                '.error',
                                '.error-message',
                                '[class*="error"]',
                            ]
                            for selector in error_selectors:
                                try:
                                    error_el = await page.query_selector(selector)
                                    if error_el:
                                        error_text = await error_el.inner_text()
                                        if error_text and len(error_text.strip()) > 0:
                                            raise PoshmarkAuthError(f"Authentication failed: {error_text.strip()[:100]}")
                                except PoshmarkAuthError:
                                    raise
                                except:
                                    pass
                        except PoshmarkAuthError:
                            raise
                        except:
                            pass
                        
                        # Capture screenshot as base64 for frontend debugging
                        screenshot_base64 = None
                        try:
                            screenshot_bytes = await page.screenshot(full_page=True)
                            import base64
                            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                            print(">>> Screenshot captured for debugging")
                        except Exception as e:
                            print(f">>> Failed to capture screenshot: {e}")
                        
                        # Try to get page title for more context
                        try:
                            page_title = await page.title()
                            print(f">>> Page title: {page_title}")
                        except:
                            pass
                        
                        raise PoshmarkAuthError(
                            "Unable to verify login status. Please reconnect your Poshmark account using the Chrome Extension.",
                            screenshot_base64=screenshot_base64
                        )
                
                # 실제 username 추출 (closet URL에 사용)
                log("Extracting username from page...")
                actual_username = username
                
                # Try multiple methods to extract username
                try:
                    # Method 1: Look for closet link (most reliable)
                    log("Trying to find closet link...")
                    closet_links = await page.query_selector_all('a[href*="/closet/"]')
                    if closet_links:
                        for link in closet_links:
                            href = await link.get_attribute("href")
                            if href:
                                import re
                                match = re.search(r"/closet/([A-Za-z0-9_\-]+)", href)
                                if match:
                                    extracted = match.group(1)
                                    if extracted and extracted != "Connected Account":
                                        actual_username = extracted
                                        log(f"✓ Extracted username from closet link: {actual_username}")
                                        break
                    
                    # Method 2: Look for user link if closet link didn't work
                    if actual_username == username or actual_username == "Connected Account":
                        log("Trying to find user link...")
                        user_links = await page.query_selector_all('a[href*="/user/"]')
                        for link in user_links:
                            href = await link.get_attribute("href")
                            if href:
                                import re
                                match = re.search(r"/user/([A-Za-z0-9_\-]+)", href)
                                if match:
                                    extracted = match.group(1)
                                    if extracted and extracted != "Connected Account":
                                        actual_username = extracted
                                        log(f"✓ Extracted username from user link: {actual_username}")
                                        break
                    
                    # Method 3: Try to get from cookies (un cookie usually has username)
                    if actual_username == username or actual_username == "Connected Account":
                        log("Trying to extract username from cookies...")
                        for cookie in cookies:
                            cookie_name = cookie.get('name', '').lower()
                            if cookie_name in ['un', 'username', 'user_name', 'user']:
                                cookie_username = cookie.get('value', '').strip()
                                if cookie_username and cookie_username != "Connected Account" and len(cookie_username) > 0:
                                    actual_username = cookie_username
                                    log(f"✓ Extracted username from cookie '{cookie_name}': {actual_username}")
                                    break
                    
                    # Method 4: Try to extract from page URL
                    if actual_username == username or actual_username == "Connected Account":
                        page_url = page.url
                        import re
                        match = re.search(r"/(?:closet|user)/([A-Za-z0-9_\-]+)", page_url)
                        if match:
                            extracted = match.group(1)
                            if extracted and extracted != "Connected Account":
                                actual_username = extracted
                                log(f"✓ Extracted username from URL: {actual_username}")
                            
                except Exception as e:
                    log(f"Error extracting username: {e}, current: {actual_username}")
                
                if actual_username == "Connected Account" or not actual_username or actual_username.strip() == "":
                    log("✗ ERROR: Could not extract valid username!")
                    raise PoshmarkAuthError("Could not determine Poshmark username. Please reconnect your account using the Chrome Extension.")
                
                log(f"Using username: {actual_username}")
                
                log(f"Navigating to closet page: {actual_username}")
                closet_url = f"https://poshmark.com/closet/{actual_username}"
                try:
                    await page.goto(closet_url, wait_until="domcontentloaded", timeout=20000)
                    log(f"Closet page loaded: {page.url}")
                    
                    # Wait for any listing links or tiles to appear (with timeout)
                    log("Waiting for listing content to load...")
                    try:
                        await page.wait_for_selector('a[href*="/listing/"]', timeout=5000, state="attached")
                        log("✓ Found listing links on page")
                    except:
                        log("⚠ No listing links found immediately, continuing...")
                    
                    # Short wait for dynamic content
                    await asyncio.sleep(1)
                except PlaywrightTimeoutError:
                    log("⚠ Warning: Page load timeout, but continuing with extraction...")
                
                log("Starting item extraction...")
                
                # Debug: Check what's actually on the page
                log("Analyzing page structure...")
                page_info = await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*="/listing/"]');
                        const tiles = document.querySelectorAll('[class*="tile"], [class*="card"], article');
                        const allLinks = document.querySelectorAll('a');
                        return {
                            listingLinks: links.length,
                            tiles: tiles.length,
                            allLinks: allLinks.length,
                            pageTitle: document.title,
                            bodyText: document.body.innerText.substring(0, 200)
                        };
                    }
                """)
                log(f"Page analysis: {page_info}")
                
                items = await page.evaluate(r"""
                    () => {
                        const items = [];
                        const seenUrls = new Set();
                        
                        // Method 1: Find all links with /listing/ in href (most reliable)
                        const allListingLinks = Array.from(document.querySelectorAll('a[href*="/listing/"]'));
                        console.log('Found', allListingLinks.length, 'listing links');
                        
                        // Also try finding by data attributes and other patterns
                        const altLinks = Array.from(document.querySelectorAll('[href*="/listing/"], [data-listing-id], [data-item-id]'));
                        console.log('Found', altLinks.length, 'alternative listing elements');
                        
                        // Combine all potential links
                        const allLinks = [...new Set([...allListingLinks, ...altLinks])];
                        console.log('Total unique links:', allLinks.length);
                        
                        allLinks.forEach((link, index) => {
                            try {
                                let url = link.href || link.getAttribute('href') || '';
                                if (!url) return;
                                
                                // Handle different URL formats
                                if (!url) {
                                    // Try to get from data attributes
                                    url = link.getAttribute('data-href') || 
                                           link.getAttribute('data-url') ||
                                           link.getAttribute('href') || '';
                                }
                                
                                // Make absolute URL if relative
                                if (url && url.startsWith('/')) {
                                    url = 'https://poshmark.com' + url;
                                }
                                
                                if (!url || !url.includes('/listing/')) {
                                    // Try parent link
                                    const parentLink = link.closest('a[href*="/listing/"]');
                                    if (parentLink) {
                                        url = parentLink.href || parentLink.getAttribute('href') || '';
                                        if (url && url.startsWith('/')) {
                                            url = 'https://poshmark.com' + url;
                                        }
                                    } else {
                                        return; // Skip if no valid URL
                                    }
                                }
                                
                                // Skip if we've seen this URL
                                if (seenUrls.has(url)) return;
                                seenUrls.add(url);
                                
                                // Extract listing ID from URL
                                const listingIdMatch = url.match(/\/listing\/([^\/\?]+)/);
                                if (!listingIdMatch) return;
                                const listingId = listingIdMatch[1];
                                
                                // Find the card/container element
                                let card = link;
                                let parent = link.parentElement;
                                let attempts = 0;
                                while (parent && attempts < 5) {
                                    if (parent.tagName === 'ARTICLE' || 
                                        parent.classList.contains('tile') ||
                                        parent.classList.contains('card') ||
                                        parent.querySelector('img')) {
                                        card = parent;
                                        break;
                                    }
                                    parent = parent.parentElement;
                                    attempts++;
                                }
                                
                                // Extract title
                                let title = '';
                                const titleSelectors = [
                                    '.title', '[class*="title"]', 'h3', 'h4', 
                                    '.item-title', '[data-testid*="title"]',
                                    'span[class*="title"]', 'div[class*="title"]'
                                ];
                                
                                for (const selector of titleSelectors) {
                                    const titleEl = card.querySelector(selector) || link.querySelector(selector);
                                    if (titleEl) {
                                        title = (titleEl.innerText || titleEl.textContent || '').trim();
                                        if (title) break;
                                    }
                                }
                                
                                // Fallback: extract from URL
                                if (!title) {
                                    title = listingId.replace(/-/g, ' ').replace(/_/g, ' ');
                                }
                                
                                // Extract price
                                let price = 0;
                                const priceSelectors = [
                                    '.price', '.amount', '[class*="price"]', 
                                    '[class*="amount"]', '[data-testid*="price"]',
                                    'span[class*="price"]', 'div[class*="price"]'
                                ];
                                
                                for (const selector of priceSelectors) {
                                    const priceEl = card.querySelector(selector) || link.querySelector(selector);
                                    if (priceEl) {
                                        const priceText = (priceEl.innerText || priceEl.textContent || '').trim();
                                        const priceMatch = priceText.match(/[\d.]+/);
                                        if (priceMatch) {
                                            price = parseFloat(priceMatch[0]);
                                            break;
                                        }
                                    }
                                }
                                
                                // Extract image
                                let imageUrl = '';
                                const imgEl = card.querySelector('img') || link.querySelector('img');
                                if (imgEl) {
                                    imageUrl = imgEl.src || imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '';
                                }
                                
                                items.push({
                                    title: title || `Item ${index + 1}`,
                                    price: price || 0,
                                    url: url,
                                    imageUrl: imageUrl || '',
                                    sku: `poshmark-${listingId}`,
                                    listingId: listingId
                                });
                            } catch (e) {
                                console.error('Error extracting item:', e);
                            }
                        });
                        
                        console.log('Extracted', items.length, 'items');
                        return items;
                    }
                """)
                
                log(f"Extraction complete: Found {len(items)} items")
                
                if len(items) == 0:
                    # Enhanced debugging
                    log("⚠ No items found! Collecting detailed debug info...")
                    try:
                        # Get more page info
                        debug_info = await page.evaluate("""
                            () => {
                                const allLinks = document.querySelectorAll('a');
                                const listingLinks = document.querySelectorAll('a[href*="/listing/"]');
                                const images = document.querySelectorAll('img');
                                const hrefs = Array.from(allLinks).slice(0, 20).map(a => a.href || a.getAttribute('href') || '').filter(h => h);
                                return {
                                    allLinks: allLinks.length,
                                    listingLinks: listingLinks.length,
                                    images: images.length,
                                    sampleHrefs: hrefs,
                                    bodyText: document.body.innerText.substring(0, 500)
                                };
                            }
                        """)
                        log(f"Debug info: {debug_info}")
                    except Exception as e:
                        log(f"Debug info collection failed: {e}")
                    
                    log("⚠ Warning: No items found. The page structure may have changed.")
                
                return items
                
            finally:
                log("Closing browser...")
                await browser.close()
                log(f"✓ Complete! Total time: {time.time() - start_time:.1f}s")
    except PoshmarkAuthError:
        log(f"✗ Authentication error after {time.time() - start_time:.1f}s")
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        log(f"✗ Error after {time.time() - start_time:.1f}s: {error_details}")
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


async def verify_poshmark_cookie(cookie_str: str) -> dict:
    """
    Verify a Poshmark session cookie by making a simple HTTP request using the cookie string.
    Returns a dict with user info (e.g., username) if verification succeeds, otherwise raises PoshmarkAuthError.
    This is a lightweight alternative to Playwright when the site can be probed via HTTP.
    """
    logger = logging.getLogger("resalehub.poshmark")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": cookie_str,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get("https://poshmark.com/", headers=headers)
        except Exception as e:
            logger.exception("poshmark: cookie verification request failed: %s", e)
            raise PoshmarkAuthError(f"Cookie verification request failed: {e}")

    if resp.status_code != 200:
        logger.info("poshmark: cookie check returned status %s", resp.status_code)
        raise PoshmarkAuthError("Cookie did not produce an authenticated response")

    text = resp.text or ""
    import re
    m = re.search(r"/user/([A-Za-z0-9_\-]+)", text)
    if m:
        username = m.group(1)
        logger.info("poshmark: cookie appears valid for user %s", username)
        return {"username": username}

    if "Sign Out" in text or "Log Out" in text or "Sign out" in text:
        logger.info("poshmark: cookie appears valid (logout link found)")
        return {"username": None}

    logger.info("poshmark: cookie verification did not find logged-in indicators")
    raise PoshmarkAuthError("Cookie did not indicate a logged-in session")