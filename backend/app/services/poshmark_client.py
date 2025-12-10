# app/services/poshmark_client.py
"""
Poshmark Playwright 자동화 클라이언트
- 자동 로그인
- 리스팅 업로드 (제목/설명/가격/카테고리/이미지)
- 발행
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


async def verify_poshmark_credentials(username: str, password: str) -> bool:
    """
    Poshmark 자격 증명 검증 (연결 시 사용)
    실제 로그인을 시도하여 자격 증명이 유효한지 확인합니다.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            try:
                # 로그인 시도
                login_success = await login_to_poshmark(page, username, password)
                return login_success
            finally:
                await browser.close()
    except Exception as e:
        print(f">>> Credential verification error: {e}")
        return False


async def login_to_poshmark(page: Page, username: str, password: str) -> bool:
    """
    Poshmark에 로그인
    Returns: 성공 여부
    """
    try:
        print(f">>> Navigating to Poshmark login page...")
        # 더 긴 타임아웃과 domcontentloaded 사용 (더 빠른 로드)
        await page.goto("https://poshmark.com/login", wait_until="domcontentloaded", timeout=60000)
        
        # 페이지가 완전히 로드될 때까지 추가 대기
        await page.wait_for_load_state("networkidle", timeout=30000)
        print(f">>> Page loaded, current URL: {page.url}")
        
        # 로그인 폼 찾기 (더 많은 셀렉터 옵션)
        print(f">>> Looking for login form...")
        
        # 이메일/사용자명 입력 필드 - 더 많은 셀렉터 옵션
        email_selectors = [
            'input[type="email"]',
            'input[type="text"][name*="email" i]',
            'input[type="text"][name*="username" i]',
            'input[name="login_form[username_email]"]',
            'input[id*="email" i]',
            'input[id*="username" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]',
            'input[placeholder*="Email" i]',
            'input[placeholder*="Username" i]',
            'input[autocomplete="username"]',
            'input[autocomplete="email"]',
        ]
        
        email_field = None
        for selector in email_selectors:
            try:
                email_field = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if email_field:
                    print(f">>> Found email field with selector: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not email_field:
            # 페이지 스크린샷 저장 (디버깅용)
            try:
                await page.screenshot(path="/tmp/poshmark_login_page.png", full_page=True)
                print(f">>> Screenshot saved to /tmp/poshmark_login_page.png for debugging")
            except:
                pass
            
            # 페이지 HTML 일부 출력
            try:
                body_text = await page.evaluate("() => document.body.innerText")
                print(f">>> Page body text (first 500 chars): {body_text[:500]}")
            except:
                pass
            
            raise PoshmarkAuthError(
                "Could not find email/username input field on Poshmark login page. "
                "The page structure may have changed."
            )
        
        await email_field.fill(username)
        print(f">>> Filled username/email")
        
        # 비밀번호 입력 필드 - 더 많은 옵션
        password_selectors = [
            'input[type="password"]',
            'input[name*="password" i]',
            'input[id*="password" i]',
            'input[autocomplete="current-password"]',
        ]
        
        password_field = None
        for selector in password_selectors:
            try:
                password_field = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if password_field:
                    print(f">>> Found password field with selector: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not password_field:
            raise PoshmarkAuthError("Could not find password input field on Poshmark login page")
        
        await password_field.fill(password)
        print(f">>> Filled password")
        
        # 로그인 버튼 찾기 - 더 많은 옵션
        login_button_selectors = [
            'button[type="submit"]',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
            'button:has-text("Sign In")',
            'button:has-text("Login")',
            'input[type="submit"]',
            'button[class*="login" i]',
            'button[class*="sign" i]',
            'form button',
        ]
        
        login_button = None
        for selector in login_button_selectors:
            try:
                login_button = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if login_button:
                    print(f">>> Found login button with selector: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not login_button:
            raise PoshmarkAuthError("Could not find login button on Poshmark login page")
        
        await login_button.click()
        print(f">>> Clicked login button")
        
        # 로그인 완료 대기 (리다이렉트 또는 대시보드 로드)
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except:
            # networkidle이 실패해도 계속 진행
            await asyncio.sleep(3)
        
        # 로그인 성공 확인 (URL이 /login이 아니거나, 사용자 메뉴가 보이면 성공)
        current_url = page.url
        print(f">>> After login, current URL: {current_url}")
        
        if "/login" not in current_url.lower() and "login" not in current_url.lower():
            print(f">>> Login successful, redirected to: {current_url}")
            return True
        
        # 또는 사용자 프로필/메뉴 확인
        user_menu_selectors = [
            'a[href*="/user/"]',
            'a[href*="/closet/"]',
            'button[aria-label*="Account" i]',
            '[data-testid*="user" i]',
            '[class*="user-menu" i]',
            '[class*="profile" i]',
            'nav a[href*="/user/"]',
        ]
        
        for selector in user_menu_selectors:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                print(f">>> Login successful, found user menu with: {selector}")
                return True
            except PlaywrightTimeoutError:
                continue
        
        # 에러 메시지 확인
        error_selectors = [
            '.error',
            '[class*="error" i]',
            '[class*="alert" i]',
            '[role="alert"]',
            'text=/invalid|incorrect|wrong|failed/i',
        ]
        for selector in error_selectors:
            try:
                error_element = await page.query_selector(selector)
                if error_element:
                    error_text = await error_element.inner_text()
                    if error_text and len(error_text.strip()) > 0:
                        raise PoshmarkAuthError(f"Login failed: {error_text}")
            except PoshmarkAuthError:
                raise
            except:
                pass
        
        # URL이 여전히 /login이면 실패로 간주
        if "/login" in current_url.lower():
            raise PoshmarkAuthError("Login appears to have failed - still on login page")
        
        print(f">>> Login status unclear, but not on login page - assuming success")
        return True
        
    except PlaywrightTimeoutError as e:
        error_msg = str(e)
        # 더 자세한 에러 메시지
        if "wait_for_selector" in error_msg:
            raise PoshmarkAuthError(
                f"Login timeout: Could not find login form elements. "
                f"Poshmark page structure may have changed. Error: {error_msg}"
            )
        raise PoshmarkAuthError(f"Login timeout: {error_msg}")
    except PoshmarkAuthError:
        raise
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
        # 여러 URL 시도 (Poshmark는 여러 경로를 사용할 수 있음)
        listing_urls = [
            "https://poshmark.com/listing/new",
            "https://poshmark.com/sell",
            "https://poshmark.com/closet/new",
        ]
        
        page_loaded = False
        for url in listing_urls:
            try:
                print(f">>> Trying URL: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                
                # 리스팅 페이지인지 확인
                current_url = page.url
                if "listing" in current_url.lower() or "sell" in current_url.lower() or "new" in current_url.lower():
                    print(f">>> Successfully loaded listing page: {current_url}")
                    page_loaded = True
                    break
            except Exception as e:
                print(f">>> Failed to load {url}: {e}")
                continue
        
        if not page_loaded:
            raise PoshmarkPublishError("Could not access Poshmark listing page")
        
        # 페이지가 완전히 로드될 때까지 추가 대기
        await asyncio.sleep(2)
        
        # 2. 이미지 업로드
        if listing_images:
            print(f">>> Uploading {len(listing_images)} images...")
            
            # 이미지 파일 input 찾기 - 더 많은 셀렉터 옵션
            image_input_selectors = [
                'input[type="file"][accept*="image"]',
                'input[type="file"]',
                'input[accept*="image"]',
                'input[class*="upload" i]',
                'input[id*="upload" i]',
                'input[name*="image" i]',
                'input[name*="photo" i]',
                'input[name*="file" i]',
            ]
            
            file_input = None
            for selector in image_input_selectors:
                try:
                    file_input = await page.wait_for_selector(selector, timeout=5000, state="visible")
                    if file_input:
                        print(f">>> Found image upload input with selector: {selector}")
                        break
                except PlaywrightTimeoutError:
                    continue
            
            if file_input:
                # 이미지 다운로드 및 임시 파일로 저장
                
                temp_files = []
                try:
                    for img in listing_images[:8]:  # Poshmark는 최대 8장
                        img_url = f"{base_url}{settings.media_url}/{img.file_path}"
                        print(f">>> Downloading image: {img_url}")
                        
                        async with httpx.AsyncClient() as client:
                            response = await client.get(img_url, timeout=30.0)
                            if response.status_code == 200:
                                # 임시 파일 생성
                                suffix = os.path.splitext(img.file_path)[1] or '.jpg'
                                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                                temp_file.write(response.content)
                                temp_file.close()
                                temp_files.append(temp_file.name)
                                print(f">>> Downloaded image to: {temp_file.name}")
                    
                    if temp_files:
                        # 파일 업로드
                        await file_input.set_input_files(temp_files)
                        print(f">>> Uploaded {len(temp_files)} images")
                        
                        # 업로드 완료 대기
                        await asyncio.sleep(2)
                finally:
                    # 임시 파일 정리
                    for temp_file in temp_files:
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
            else:
                print(f">>> Image upload input not found, continuing without images...")
                # 이미지 없이도 계속 진행 (Poshmark는 이미지가 필수일 수 있지만 시도)
        
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
        print(f">>> Looking for publish button...")
        
        # 페이지가 완전히 로드될 때까지 대기
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)  # 추가 대기 (동적 콘텐츠 로드)
        
        publish_selectors = [
            'button:has-text("Publish")',
            'button:has-text("List Item")',
            'button:has-text("List")',
            'button:has-text("Post")',
            'button:has-text("Share")',
            'button[type="submit"]',
            'button[type="submit"]:has-text("Publish")',
            'button[type="submit"]:has-text("List")',
            'button[type="submit"]:has-text("Post")',
            '[data-testid*="publish" i]',
            '[data-testid*="submit" i]',
            '[data-testid*="list" i]',
            '[data-testid*="post" i]',
            'button[class*="publish" i]',
            'button[class*="submit" i]',
            'button[class*="list" i]',
            'button[class*="post" i]',
            'a:has-text("Publish")',
            'a:has-text("List")',
            '[role="button"]:has-text("Publish")',
            '[role="button"]:has-text("List")',
            'form button[type="submit"]',
            'form button:last-child',
        ]
        
        publish_button = None
        used_selector = None
        
        for selector in publish_selectors:
            try:
                publish_button = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if publish_button:
                    # 버튼이 보이는지 확인
                    is_visible = await publish_button.is_visible()
                    if is_visible:
                        used_selector = selector
                        print(f">>> Found publish button with selector: {selector}")
                        break
                    else:
                        publish_button = None
            except PlaywrightTimeoutError:
                continue
            except Exception as e:
                print(f">>> Error checking selector {selector}: {e}")
                continue
        
        if not publish_button:
            # 디버깅: 페이지 스크린샷 및 HTML 일부 저장
            try:
                await page.screenshot(path="/tmp/poshmark_listing_page.png", full_page=True)
                print(f">>> Screenshot saved to /tmp/poshmark_listing_page.png")
            except:
                pass
            
            # 페이지의 모든 버튼 찾기
            try:
                all_buttons = await page.evaluate("""
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button, a[role="button"], [role="button"]'));
                        return buttons.map(btn => ({
                            text: btn.innerText.trim(),
                            type: btn.type || '',
                            className: btn.className || '',
                            id: btn.id || '',
                            visible: btn.offsetParent !== null
                        })).filter(btn => btn.visible && btn.text.length > 0);
                    }
                """)
                print(f">>> Found {len(all_buttons)} visible buttons on page:")
                for btn in all_buttons[:10]:  # 처음 10개만 출력
                    print(f">>>   - Text: '{btn['text']}', Type: {btn['type']}, Class: {btn['className'][:50]}")
            except Exception as e:
                print(f">>> Could not list buttons: {e}")
            
            raise PoshmarkPublishError(
                "Could not find publish button on Poshmark listing page. "
                "The page structure may have changed. Check screenshot at /tmp/poshmark_listing_page.png"
            )
        
        # 버튼 클릭
        try:
            # 스크롤하여 버튼이 보이도록
            await publish_button.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            
            # 클릭 시도
            await publish_button.click(timeout=10000)
            print(f">>> Clicked publish button: {used_selector}")
            
            # 페이지 로드 대기
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except:
                await asyncio.sleep(3)  # networkidle 실패 시에도 대기
                
        except Exception as e:
            raise PoshmarkPublishError(f"Failed to click publish button: {str(e)}")
        
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
    
    try:
        async with async_playwright() as p:
            # 브라우저 실행 (headless=False로 디버깅 가능)
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as e:
                if "Executable doesn't exist" in str(e) or "BrowserType.launch" in str(e):
                    raise PoshmarkPublishError(
                        "Playwright browser not installed. Please run 'playwright install chromium' "
                        "or restart the server to auto-install browsers."
                    )
                raise
            
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
                try:
                    await browser.close()
                except:
                    pass
    except PoshmarkPublishError:
        raise
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "BrowserType.launch" in str(e):
            raise PoshmarkPublishError(
                "Playwright browser not installed. Please run 'playwright install chromium' "
                "or restart the server to auto-install browsers."
            )
        raise PoshmarkPublishError(f"Failed to launch browser: {str(e)}")

