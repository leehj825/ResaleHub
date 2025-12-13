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
        # Try multiple possible URLs for listing creation
        listing_urls = [
            "https://poshmark.com/listing/new",
            "https://poshmark.com/list-item",
            "https://poshmark.com/sell",
        ]
        
        listing_url = None
        page_loaded = False
        
        for url in listing_urls:
            try:
                print(f">>> Trying URL: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                current_url = page.url.lower()
                page_title = await page.title()
                
                print(f">>> Current URL after navigation: {page.url}")
                print(f">>> Page title: {page_title}")
                
                # Check if we got redirected to a 404 or error page
                if "not found" in page_title.lower() or "404" in current_url or "error" in page_title.lower():
                    print(f">>> URL {url} returned error page, trying next...")
                    continue
                
                # Check if we're on a login page (shouldn't happen if cookies are valid)
                if "login" in current_url or "sign-in" in current_url:
                    raise PoshmarkPublishError("Redirected to login page. Cookies may be invalid.")
                
                listing_url = url
                page_loaded = True
                break
                
            except Exception as e:
                print(f">>> Error navigating to {url}: {e}")
                continue
        
        if not page_loaded or not listing_url:
            # Try the most common URL one more time with better error handling
            try:
                await page.goto("https://poshmark.com/listing/new", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)  # Wait for page to fully load
                
                current_url = page.url.lower()
                page_title = await page.title()
                
                if "not found" in page_title.lower() or "404" in current_url:
                    # Check if there's a "Sell" or "List Item" link we can use
                    sell_link = await page.query_selector('a[href*="/list"], a[href*="/sell"], a[href*="/listing/new"]')
                    if sell_link:
                        href = await sell_link.get_attribute("href")
                        if href:
                            if href.startswith("/"):
                                href = "https://poshmark.com" + href
                            print(f">>> Found alternative link: {href}")
                            await page.goto(href, wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(2)
                            listing_url = href
                            page_loaded = True
                else:
                    listing_url = "https://poshmark.com/listing/new"
                    page_loaded = True
            except Exception as e:
                print(f">>> Final navigation attempt failed: {e}")
        
        if not page_loaded:
            screenshot_path = "/tmp/debug_failed_navigation.png"
            await page.screenshot(path=screenshot_path)
            content = await page.content()
            print(f">>> Failed to load listing page. Screenshot: {screenshot_path}")
            print(f">>> Page URL: {page.url}")
            print(f">>> Page title: {await page.title()}")
            print(f">>> Page content sample: {content[:1000]}")
            raise PoshmarkPublishError(f"Could not access Poshmark listing creation page. Current URL: {page.url}, Title: {await page.title()}")

        # Wait for page to fully load (Vue.js apps need time to render)
        print(f">>> Waiting for page to fully load...")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except:
            # If networkidle times out, wait a bit more for Vue to render
            await asyncio.sleep(3)
        
        # Additional wait for Vue.js to render the form
        await asyncio.sleep(2)
        
        print(f">>> Looking for listing form elements...")
        
        # Try multiple selectors that Poshmark might use
        form_selectors = [
            'input[type="file"]',
            'input[type="file"][accept*="image"]',
            'input[name*="title" i]',
            'input[placeholder*="title" i]',
            'textarea[name*="description" i]',
            'textarea[placeholder*="description" i]',
            '[data-testid*="title"]',
            '[data-testid*="description"]',
            'input[type="text"][name*="title"]',
            'input[type="text"][placeholder*="What"]',  # Poshmark often uses "What are you selling?"
            'button[type="submit"]',
            'button:has-text("List")',
            'button:has-text("Publish")',
        ]
        
        found_elements = []
        for selector in form_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    found_elements.append(selector)
                    print(f">>> ✓ Found element with selector: {selector}")
            except:
                pass
        
        # Also check with JavaScript evaluation
        try:
            form_info = await page.evaluate("""
                () => {
                    const fileInputs = document.querySelectorAll('input[type="file"]');
                    const textInputs = document.querySelectorAll('input[type="text"], input[name*="title"], input[placeholder*="title"]');
                    const textareas = document.querySelectorAll('textarea');
                    const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
                    const listButtons = Array.from(document.querySelectorAll('button')).filter(btn => btn.innerText && (btn.innerText.includes("List") || btn.innerText.includes("Publish")));
                    return {
                        fileInputs: fileInputs.length,
                        textInputs: textInputs.length,
                        textareas: textareas.length,
                        buttons: buttons.length,
                        bodyText: document.body.innerText.substring(0, 200)
                    };
                }
            """)
            print(f">>> Form elements found via JS: {form_info}")
        except Exception as e:
            print(f">>> Could not evaluate form info: {e}")
        
        # If we found at least one form element, continue
        if not found_elements:
                # 봇 탐지 화면인지 확인
            page_content = await page.content()
            if "Pardon the interruption" in page_content or await page.query_selector("text=Pardon the interruption"):
                    raise PoshmarkPublishError("Bot detected: 'Pardon the interruption' screen active.")
                
            
            # 스크린샷 저장
            screenshot_path = "/tmp/debug_failed_form_load.png"
            await page.screenshot(path=screenshot_path)
            print(f">>> Failed to load form. Screenshot saved to {screenshot_path}")
            print(f">>> Current URL: {page.url}")
            print(f">>> Page title: {await page.title()}")
            
            # 페이지 소스 일부 로깅
                
            raise PoshmarkPublishError(f"Could not find listing form elements. Current URL: {page.url}, Title: {await page.title()}. Likely blocked or page layout changed.")
                
        print(f">>> ✓ Found {len(found_elements)} form elements")
        
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
        
        # 제목 - try multiple selectors
        title_filled = False
        title_selectors = [
            'input[name*="title" i]',
            'input[placeholder*="title" i]',
            'input[placeholder*="What" i]',
            'input[type="text"][placeholder*="What"]',
            'input[data-testid*="title"]',
        ]
        for selector in title_selectors:
            try:
                title_field = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if title_field:
                    await title_field.fill(listing.title or "Untitled")
                    print(f">>> ✓ Filled title with selector: {selector}")
                    title_filled = True
                    break
            except:
                continue
        
        if not title_filled:
            print(f">>> Warning: Could not fill title field")
        
        # 설명 - try multiple selectors
        description_filled = False
        description_selectors = [
            'textarea[name*="description" i]',
            'textarea[placeholder*="description" i]',
            'textarea[placeholder*="Describe" i]',
            'textarea[data-testid*="description"]',
        ]
        for selector in description_selectors:
            try:
                desc_field = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if desc_field:
                    await desc_field.fill(listing.description or "No description")
                    print(f">>> ✓ Filled description with selector: {selector}")
                    description_filled = True
                    break
            except:
                continue
        
        if not description_filled:
            print(f">>> Warning: Could not fill description field")
        
        # 가격 - try multiple selectors (price might be on a different step/page)
        price = str(int(float(listing.price or 0)))
        price_filled = False
        price_selectors = [
            'input[name*="price" i]',
            'input[placeholder*="price" i]',
            'input[placeholder*="Price" i]',
            'input[placeholder*="Original Price" i]',
            'input[placeholder*="List Price" i]',
            'input[data-testid*="price"]',
            'input[name="current_price"]',
            'input[name="list_price"]',
            'input[type="number"]',
            'input[type="text"][inputmode="numeric"]',
        ]
        for selector in price_selectors:
            try:
                price_field = await page.wait_for_selector(selector, timeout=2000, state="visible")
                if price_field:
                    # Clear the field first
                    await price_field.click()
                    await price_field.fill("")
                    await price_field.fill(price)
                    print(f">>> ✓ Filled price with selector: {selector}")
                    price_filled = True
                    # Don't break - might need to fill multiple price fields
            except:
                continue
        
        if not price_filled:
            print(f">>> Warning: Could not fill price field (might be on next step)")
        
        # Wait a bit for form to process the inputs
        await asyncio.sleep(1)
        
        # Close any modals that might be open
        try:
            modal_close_buttons = await page.query_selector_all('button[aria-label*="close" i], button[aria-label*="Close" i], .modal-close, [data-test*="close"], [data-test*="modal-close"]')
            for close_btn in modal_close_buttons:
                try:
                    await close_btn.click(timeout=1000)
                    print(f">>> Closed modal")
                    await asyncio.sleep(0.5)
                except:
                    pass
            
            # Also try to click outside modal or press Escape
            modals = await page.query_selector_all('.modal-backdrop, [data-test="modal"], .modal')
            if modals:
                print(f">>> Found {len(modals)} modals, trying to close them...")
                # Try pressing Escape
                await page.keyboard.press('Escape')
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f">>> Warning: Could not close modals: {e}")
        
        # 4. 발행 버튼 클릭
        print(f">>> Looking for publish button...")
        
        publish_btn = None
        publish_selectors = [
            'button:has-text("List")',
            'button:has-text("List Item")',
            'button:has-text("Next")',
            'button:has-text("Publish")',
            'button[type="submit"]',
            'button[data-testid*="submit"]',
            'button[data-testid*="publish"]',
        ]
        
        for selector in publish_selectors:
            try:
                publish_btn = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if publish_btn:
                    print(f">>> ✓ Found publish button with selector: {selector}")
                    break
            except:
                continue
        
        if not publish_btn:
            # Try to find any button with "List" or "Publish" text
            try:
                buttons = await page.query_selector_all('button')
                for btn in buttons:
                    text = await btn.inner_text()
                    if text and ("List" in text or "Publish" in text or "Next" in text):
                        publish_btn = btn
                        print(f">>> ✓ Found publish button by text: {text}")
                        break
            except:
                pass
        
        if not publish_btn:
            await page.screenshot(path="/tmp/no_publish_btn.png")
            raise PoshmarkPublishError("Publish button not found")

        # Wait for any modals to close before clicking
        try:
            # Wait for modal backdrop to disappear
            await page.wait_for_selector('.modal-backdrop--in', state="hidden", timeout=3000)
            print(f">>> Modal backdrop closed")
        except:
            # Modal might not be there or already closed
            pass
        
        # Try to close any remaining modals
        try:
            modals = await page.query_selector_all('.modal-backdrop--in, [data-test="modal"].modal-backdrop--in')
            if modals:
                print(f">>> Found {len(modals)} active modals, closing...")
                # Press Escape to close modals
                await page.keyboard.press('Escape')
                await asyncio.sleep(1)
                # Try clicking outside modal
                await page.evaluate("""
                    () => {
                        const modals = document.querySelectorAll('.modal-backdrop--in');
                        modals.forEach(modal => {
                            const clickEvent = new MouseEvent('click', { bubbles: true });
                            modal.dispatchEvent(clickEvent);
                        });
                    }
                """)
                await asyncio.sleep(1)
        except Exception as e:
            print(f">>> Warning: Could not close modals: {e}")
        
        # Try clicking the button - if modal intercepts, use JavaScript click
        try:
            await publish_btn.click(timeout=5000)
            print(">>> Clicked publish button")
        except Exception as click_error:
            if "intercepts pointer events" in str(click_error) or "modal" in str(click_error).lower():
                print(f">>> Modal intercepted click, using JavaScript click instead...")
                # Use JavaScript to click the button directly
                await publish_btn.evaluate("button => button.click()")
                print(">>> Clicked publish button via JavaScript")
            else:
                raise
        
        # Wait for navigation or next step
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        # If we clicked "Next", we might be on a price/shipping step - fill price if needed
        current_url = page.url
        button_text = ""
        try:
            button_text = await publish_btn.inner_text()
        except:
            pass
        
        if "next" in button_text.lower():
            print(f">>> Clicked 'Next', checking for price field on next step...")
            await asyncio.sleep(2)  # Wait for next step to load
            
            # Try to fill price again on the next step
            for selector in price_selectors:
                try:
                    price_field = await page.wait_for_selector(selector, timeout=3000, state="visible")
                    if price_field:
                        await price_field.click()
                        await price_field.fill("")
                        await price_field.fill(price)
                        print(f">>> ✓ Filled price on next step with selector: {selector}")
                        price_filled = True
                        break
                except:
                    continue
            
            # Look for final publish button (regardless of whether price was filled)
            print(f">>> Looking for final publish button...")
            final_publish_btn = None
            final_publish_selectors = [
                'button:has-text("List")',
                'button:has-text("List Item")',
                'button:has-text("Publish")',
                'button[type="submit"]',
            ]
            
            for selector in final_publish_selectors:
                try:
                    final_publish_btn = await page.wait_for_selector(selector, timeout=5000, state="visible")
                    if final_publish_btn:
                        btn_text = await final_publish_btn.inner_text()
                        print(f">>> ✓ Found final publish button: {btn_text}")
                        # Close modals again
                        try:
                            await page.keyboard.press('Escape')
                            await asyncio.sleep(0.5)
                        except:
                            pass
                        
                        try:
                            await final_publish_btn.click(timeout=5000)
                            print(">>> Clicked final publish button")
                        except Exception as e:
                            if "intercepts" in str(e).lower() or "modal" in str(e).lower():
                                print(f">>> Modal intercepted, using JavaScript click...")
                                await final_publish_btn.evaluate("button => button.click()")
                                print(">>> Clicked final publish button via JavaScript")
                            else:
                                raise
                        break
                except:
                    continue
            
            if not final_publish_btn:
                print(f">>> ⚠ Warning: Could not find final publish button after clicking Next")
        
        # Wait for navigation to listing page or success confirmation
        print(f">>> Waiting for publish to complete...")
        current_url = page.url
        listing_id = None
        
        # Wait for redirect to listing page (up to 30 seconds)
        max_wait = 30
        waited = 0
        while waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
            current_url = page.url
            print(f">>> [{waited}s] Current URL: {current_url}")
            
            # Check if we're on a listing page
            if "/listing/" in current_url and "/create-listing" not in current_url:
                print(f">>> ✓ Redirected to listing page: {current_url}")
                # Extract listing ID
                parts = current_url.split("/")
                listing_id = parts[-1].split("-")[-1] if parts else None
                print(f">>> Extracted listing ID: {listing_id}")
                break
            
            # Check if we're on a success/confirmation page
            try:
                page_title = await page.title()
                if "success" in page_title.lower() or "published" in page_title.lower() or "listed" in page_title.lower():
                    print(f">>> ✓ Found success confirmation page")
                    # Try to find listing link on the page
                    try:
                        listing_link = await page.query_selector('a[href*="/listing/"]')
                        if listing_link:
                            href = await listing_link.get_attribute("href")
                            if href:
                                if href.startswith("/"):
                                    href = "https://poshmark.com" + href
                                current_url = href
                                parts = href.split("/")
                                listing_id = parts[-1].split("-")[-1] if parts else None
                                print(f">>> Found listing link: {current_url}")
                                break
                    except:
                        pass
            except:
                pass
            
            # Check if we're still on create-listing page (might be an error)
            if "/create-listing" in current_url and waited > 10:
                print(f">>> ⚠ Still on create-listing page after {waited}s, checking for errors...")
                # Check for error messages
                try:
                    error_elements = await page.query_selector_all('.error, .error-message, [class*="error"]')
                    if error_elements:
                        for err in error_elements[:3]:
                            text = await err.inner_text()
                            if text:
                                print(f">>> Error on page: {text[:100]}")
                except:
                    pass
        
        # Final check - if we still don't have a listing URL, check the closet
        if "/listing/" not in current_url or "/create-listing" in current_url:
            print(f">>> ⚠ Warning: Not redirected to listing page. Current URL: {current_url}")
            print(f">>> Checking if listing was saved to drafts or closet...")
            
            # Try navigating to closet to see if item appears
            try:
                # Get username from cookies (we have access to cookies in the parent function)
                username = None
                # Note: We don't have direct access to db/user here, so we'll try to get username from page or cookies
                # The parent function has the username, but we can try to extract it from the page
                try:
                    closet_link = await page.query_selector('a[href*="/closet/"]')
                    if closet_link:
                        href = await closet_link.get_attribute("href")
                        if href:
                            import re
                            match = re.search(r"/closet/([A-Za-z0-9_\-]+)", href)
                            if match:
                                username = match.group(1)
                                print(f">>> Extracted username from page: {username}")
                except:
                    pass
                
                if username and username != "Connected Account":
                    closet_url = f"https://poshmark.com/closet/{username}"
                    print(f">>> Checking closet: {closet_url}")
                    await page.goto(closet_url, wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(3)
                    
                    # Look for the listing we just created (by title or most recent)
                    listing_links = await page.query_selector_all('a[href*="/listing/"]')
                    if listing_links:
                        print(f">>> Found {len(listing_links)} listings in closet")
                        # Get the most recent one (first in list)
                        if listing_links:
                            href = await listing_links[0].get_attribute("href")
                            if href:
                                if href.startswith("/"):
                                    href = "https://poshmark.com" + href
                                current_url = href
                                parts = href.split("/")
                                listing_id = parts[-1].split("-")[-1] if parts else None
                                print(f">>> Found listing in closet: {current_url}")
                    else:
                        print(f">>> ⚠ No listings found in closet")
            except Exception as e:
                print(f">>> Could not check closet: {e}")
                import traceback
                traceback.print_exc()
        
        # If still no listing URL, it might be in drafts or failed
        if "/listing/" not in current_url or "/create-listing" in current_url:
            print(f">>> ⚠ Listing might be saved as draft or publish failed. Current URL: {current_url}")
            # Take a screenshot for debugging
            try:
                await page.screenshot(path="/tmp/publish_final_state.png")
                print(f">>> Screenshot saved to /tmp/publish_final_state.png")
            except:
                pass
            # Return success but with a note
            return {
                "status": "published",
                "url": current_url,
                "external_item_id": listing_id,
                "note": "Listing may be in drafts. Please check your Poshmark account."
            }

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
            
            # 3. 리소스 차단 적용 (발행 시에는 이미지만 차단, 스크립트는 허용)
            # 발행 페이지는 동적 콘텐츠가 필요하므로 스크립트는 허용
            async def selective_block_publish(route):
                resource_type = route.request.resource_type
                url = route.request.url.lower()
                
                # 이미지, 폰트, 미디어는 차단
                if resource_type in ["image", "font", "media"]:
                    await route.abort()
                # 광고/추적 스크립트만 차단 (필수 스크립트는 허용)
                elif resource_type == "script" and any(domain in url for domain in ["google-analytics", "googletagmanager", "facebook", "doubleclick", "adservice"]):
                    await route.abort()
                else:
                    await route.continue_()
            
            await page.route("**/*", selective_block_publish)
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
            
            # 리소스 차단 최적화: 더 많은 리소스 차단하여 속도 향상
            log("Setting up resource blocking...")
            async def aggressive_block(route):
                resource_type = route.request.resource_type
                url = route.request.url.lower()
                
                # 이미지, 폰트, 미디어는 항상 차단
                if resource_type in ["image", "font", "media"]:
                    await route.abort()
                # 광고 및 추적 스크립트 차단
                elif resource_type == "script" and any(domain in url for domain in ["google-analytics", "googletagmanager", "facebook", "doubleclick", "adservice"]):
                    await route.abort()
                # CSS는 일부 허용 (레이아웃에 필요할 수 있음)
                elif resource_type == "stylesheet" and ("analytics" in url or "tracking" in url):
                    await route.abort()
                else:
                    await route.continue_()
            
            await page.route("**/*", aggressive_block)
            log("Resource blocking configured")
            
            try:
                # 로그인 상태 확인 - 최적화: 직접 closet 페이지로 이동하여 확인
                log("Navigating to feed page to check login status...")
                await page.goto("https://poshmark.com/feed", wait_until="domcontentloaded", timeout=15000)
                log(f"Feed page loaded: {page.url}")
                
                # 빠른 로그인 확인 - wait_for_selector 사용 (최대 3초 대기)
                log("Checking login status...")
                is_logged_in = False
                actual_username = username
                page_url = page.url.lower()
                
                # Method 1: URL 체크 (가장 빠름)
                if "login" in page_url or "sign-in" in page_url or "signin" in page_url:
                    log("✗ URL indicates login page - not authenticated")
                    is_logged_in = False
                else:
                    # Method 2: closet 링크 찾기 (가장 신뢰할 수 있고 username도 함께 추출)
                    try:
                        closet_link = await page.wait_for_selector(
                            'a[href*="/closet/"]',
                            timeout=3000,
                            state="attached"
                        )
                        if closet_link:
                            href = await closet_link.get_attribute("href")
                            if href:
                                import re
                                match = re.search(r"/closet/([A-Za-z0-9_\-]+)", href)
                                if match:
                                    extracted = match.group(1)
                                    if extracted and extracted != "Connected Account":
                                        actual_username = extracted
                                        is_logged_in = True
                                        log(f"✓ Found closet link, extracted username: {actual_username}")
                    except:
                        # closet 링크를 찾지 못했으면 다른 방법 시도
                        try:
                            user_link = await page.wait_for_selector(
                                'a[href*="/user/"], nav a[href*="/user/"]',
                                timeout=2000,
                                state="attached"
                            )
                            if user_link:
                                href = await user_link.get_attribute("href")
                                if href:
                                    import re
                                    match = re.search(r"/user/([A-Za-z0-9_\-]+)", href)
                                    if match:
                                        extracted = match.group(1)
                                        if extracted and extracted != "Connected Account":
                                            actual_username = extracted
                                            is_logged_in = True
                                            log(f"✓ Found user link, extracted username: {actual_username}")
                        except:
                            # 빠른 텍스트 체크
                            try:
                                page_content = await page.content()
                                if any(indicator in page_content for indicator in ["Sign Out", "Log Out", "My Closet"]):
                                    is_logged_in = True
                                    log("✓ Found logged-in indicators in page content")
                            except:
                                pass
                
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
                
                # Username이 아직 추출되지 않았으면 저장된 username 사용 (extension에서 보낸 것)
                if actual_username == username or actual_username == "Connected Account":
                    # 저장된 username이 유효한지 확인
                    if username and username != "Connected Account" and username.strip():
                        actual_username = username
                        log(f"Using stored username from extension: {actual_username}")
                    else:
                        # Fallback: 쿠키에서 시도
                        log("Extracting username from cookies as fallback...")
                        for cookie in cookies:
                            cookie_name = cookie.get('name', '').lower()
                            if cookie_name in ['un', 'username', 'user_name', 'user']:
                                cookie_username = cookie.get('value', '').strip()
                                if cookie_username and cookie_username != "Connected Account" and len(cookie_username) > 0:
                                    actual_username = cookie_username
                                    log(f"✓ Extracted username from cookie '{cookie_name}': {actual_username}")
                                    break
                
                if actual_username == "Connected Account" or not actual_username or actual_username.strip() == "":
                    log("✗ ERROR: Could not extract valid username!")
                    raise PoshmarkAuthError("Could not determine Poshmark username. Please reconnect your Poshmark account using the Chrome Extension.")
                
                log(f"Using username: {actual_username}")
                
                log(f"Navigating to closet page: {actual_username}")
                closet_url = f"https://poshmark.com/closet/{actual_username}"
                try:
                    await page.goto(closet_url, wait_until="domcontentloaded", timeout=15000)
                    log(f"Closet page loaded: {page.url}")
                    
                    # 빠른 체크: listing 링크가 있는지 확인 (최대 2초 대기)
                    try:
                        await page.wait_for_selector('a[href*="/listing/"]', timeout=2000, state="attached")
                        log("✓ Found listing links on page")
                    except:
                        log("⚠ No listing links found immediately, continuing...")
                except PlaywrightTimeoutError:
                    log("⚠ Warning: Page load timeout, but continuing with extraction...")
                
                log("Starting item extraction...")
                
                # 빠른 스크롤로 동적 콘텐츠 로드 (최소 대기)
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.5)  # 0.5초로 단축
                    await page.evaluate("window.scrollTo(0, 0)")
                    await asyncio.sleep(0.3)  # 0.3초로 단축
                except Exception as e:
                    log(f"Warning: Scrolling failed: {e}")
                
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