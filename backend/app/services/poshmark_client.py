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


async def verify_poshmark_credentials(username: str, password: str, headless: bool = True) -> bool:
    """
    Poshmark 자격 증명 검증 (연결 시 사용)
    실제 로그인을 시도하여 자격 증명이 유효한지 확인합니다.
    빠른 검증을 위해 타임아웃을 줄입니다.
    
    Args:
        headless: False로 설정하면 브라우저를 보여줌 (디버깅용)
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            try:
                # 빠른 로그인 검증 (타임아웃 단축)
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
    빠른 Poshmark 로그인 검증 (연결 시 사용)
    타임아웃을 줄여서 빠르게 검증합니다.
    """
    try:
        print(f">>> Navigating to Poshmark login page (quick verification)...")
        # 더 짧은 타임아웃으로 페이지 로드
        await page.goto("https://poshmark.com/login", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1)  # 최소 대기
        
        # 이메일/사용자명 입력 필드 찾기 (빠른 검증)
        email_selectors = [
            'input[type="email"]',
            'input[type="text"][name*="email" i]',
            'input[type="text"][name*="username" i]',
            'input[name="login_form[username_email]"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]',
        ]
        
        email_field = None
        for selector in email_selectors:
            try:
                email_field = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if email_field:
                    print(f">>> Found email field: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not email_field:
            raise PoshmarkAuthError("Could not find email/username input field")
        
        await email_field.fill(username)
        print(f">>> Filled username")
        
        # 비밀번호 입력 필드
        password_selectors = [
            'input[type="password"]',
            'input[name*="password" i]',
        ]
        
        password_field = None
        for selector in password_selectors:
            try:
                password_field = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if password_field:
                    print(f">>> Found password field: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not password_field:
            raise PoshmarkAuthError("Could not find password input field")
        
        await password_field.fill(password)
        print(f">>> Filled password")
        
        # 로그인 버튼 클릭
        login_button_selectors = [
            'button[type="submit"]',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
        ]
        
        login_button = None
        for selector in login_button_selectors:
            try:
                login_button = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if login_button:
                    print(f">>> Found login button: {selector}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        if not login_button:
            raise PoshmarkAuthError("Could not find login button")
        
        await login_button.click()
        print(f">>> Clicked login button")
        
        # 로그인 완료 대기 (짧은 타임아웃)
        try:
            # URL 변경 또는 에러 메시지 확인
            await page.wait_for_function(
                "() => window.location.href.indexOf('/login') === -1 || document.querySelector('.error, [class*=\"error\" i], [role=\"alert\"]') !== null",
                timeout=10000
            )
        except:
            # 타임아웃이어도 현재 URL 확인
            pass
        
        # 로그인 성공 확인
        current_url = page.url
        print(f">>> After login, URL: {current_url}")
        
        # 에러 메시지 확인
        error_selectors = [
            '.error',
            '[class*="error" i]',
            '[role="alert"]',
            'text=/invalid|incorrect|wrong|failed/i',
        ]
        for selector in error_selectors:
            try:
                error_element = await page.query_selector(selector)
                if error_element:
                    error_text = await error_element.inner_text()
                    if error_text and len(error_text.strip()) > 0:
                        print(f">>> Login error found: {error_text}")
                        raise PoshmarkAuthError(f"Login failed: {error_text}")
            except PoshmarkAuthError:
                raise
            except:
                pass
        
        # URL이 /login이 아니면 성공으로 간주
        if "/login" not in current_url.lower() and "login" not in current_url.lower():
            print(f">>> Login verification successful (redirected away from login page)")
            return True
        
        # 사용자 메뉴 확인 (빠른 확인)
        user_menu_selectors = [
            'a[href*="/user/"]',
            'a[href*="/closet/"]',
            'button[aria-label*="Account" i]',
        ]
        
        for selector in user_menu_selectors:
            try:
                await page.wait_for_selector(selector, timeout=3000)
                print(f">>> Login verification successful (found user menu)")
                return True
            except PlaywrightTimeoutError:
                continue
        
        # 여전히 로그인 페이지에 있으면 실패
        if "/login" in current_url.lower():
            raise PoshmarkAuthError("Login failed - still on login page")
        
        # 불확실하지만 로그인 페이지가 아니면 성공으로 간주
        print(f">>> Login verification successful (not on login page)")
        return True
        
    except PlaywrightTimeoutError as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            raise PoshmarkAuthError(
                f"Login verification timeout: Could not complete login within time limit. "
                f"This may indicate invalid credentials or network issues."
            )
        raise PoshmarkAuthError(f"Login timeout: {error_msg}")
    except PoshmarkAuthError:
        raise
    except Exception as e:
        raise PoshmarkAuthError(f"Login verification failed: {str(e)}")


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
        # 1. "List an Item" 페이지로 이동 (가장 일반적인 URL만 사용)
        print(f">>> Navigating to Poshmark listing page...")
        listing_url = "https://poshmark.com/listing/new"
        
        try:
            print(f">>> Loading: {listing_url}")
            # load 이벤트만 대기 (더 빠름)
            await page.goto(listing_url, wait_until="load", timeout=20000)
            
            # 리스팅 페이지인지 빠르게 확인
            current_url = page.url
            print(f">>> Loaded page: {current_url}")
            
            # 필수 요소가 나타날 때까지만 대기 (networkidle 대신)
            try:
                # 제목이나 이미지 업로드 필드가 나타나면 페이지 로드 완료로 간주
                await page.wait_for_selector(
                    'input[type="file"], input[name*="title" i], textarea[name*="description" i]',
                    timeout=10000,
                    state="attached"  # DOM에만 있으면 됨 (visible 불필요)
                )
            except PlaywrightTimeoutError:
                # 필수 요소가 없어도 계속 진행 (페이지 구조가 다를 수 있음)
                print(f">>> Warning: Could not find expected form elements, continuing anyway...")
                
        except Exception as e:
            raise PoshmarkPublishError(f"Could not access Poshmark listing page: {str(e)}")
        
        # 2. 이미지 업로드
        if listing_images:
            print(f">>> Uploading {len(listing_images)} images...")
            
            # 이미지 파일 input 찾기
            image_input_selector = 'input[type="file"][accept*="image"], input[type="file"]'
            try:
                file_input = await page.wait_for_selector(image_input_selector, timeout=3000, state="attached")
                
                if file_input:
                    # 이미지 다운로드 및 임시 파일로 저장 (병렬 처리)
                    print(f">>> Downloading {len(listing_images[:8])} images in parallel...")
                    
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
                    
                    # 병렬 다운로드
                    download_tasks = [download_image(img) for img in listing_images[:8]]
                    temp_files = [f for f in await asyncio.gather(*download_tasks) if f]
                    
                    if temp_files:
                        try:
                            # 파일 업로드
                            await file_input.set_input_files(temp_files)
                            print(f">>> Uploaded {len(temp_files)} images")
                            
                            # 업로드 완료 대기 (최소화)
                            await asyncio.sleep(1)
                        finally:
                            # 임시 파일 정리
                            for temp_file in temp_files:
                                try:
                                    os.unlink(temp_file)
                                except:
                                    pass
                    else:
                        print(f">>> Warning: No images were downloaded successfully")
            except PlaywrightTimeoutError:
                print(f">>> Image upload input not found, skipping...")
        
        # 3-5. 필수 필드 입력 (타임아웃 최소화)
        print(f">>> Filling listing details...")
        
        # 제목 입력
        title_selectors = [
            'input[name*="title" i]',
            'input[placeholder*="title" i]',
            'textarea[name*="title" i]',
            'input[type="text"]:first-of-type',
        ]
        for selector in title_selectors:
            try:
                title_field = await page.wait_for_selector(selector, timeout=3000, state="attached")
                if title_field:
                    await title_field.fill(listing.title or "Untitled")
                    print(f">>> Filled title: {listing.title}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        # 설명 입력
        description_selectors = [
            'textarea[name*="description" i]',
            'textarea[placeholder*="description" i]',
            'textarea[placeholder*="tell" i]',
            'textarea:first-of-type',
        ]
        for selector in description_selectors:
            try:
                desc_field = await page.wait_for_selector(selector, timeout=3000, state="attached")
                if desc_field:
                    await desc_field.fill(listing.description or "No description")
                    print(f">>> Filled description")
                    break
            except PlaywrightTimeoutError:
                continue
        
        # 가격 입력
        price_selectors = [
            'input[name*="price" i]',
            'input[type="number"][placeholder*="price" i]',
            'input[placeholder*="$" i]',
            'input[type="number"]',
        ]
        price = float(listing.price or 0)
        for selector in price_selectors:
            try:
                price_field = await page.wait_for_selector(selector, timeout=3000, state="attached")
                if price_field:
                    await price_field.fill(str(int(price)))
                    print(f">>> Filled price: ${price}")
                    break
            except PlaywrightTimeoutError:
                continue
        
        # 6-9. 선택적 필드 (빠르게 시도, 실패해도 계속)
        # 브랜드 입력 (있는 경우)
        if listing.brand:
            brand_selectors = ['input[name*="brand" i]', 'input[placeholder*="brand" i]']
            for selector in brand_selectors:
                try:
                    brand_field = await page.wait_for_selector(selector, timeout=2000, state="attached")
                    if brand_field:
                        await brand_field.fill(listing.brand)
                        print(f">>> Filled brand: {listing.brand}")
                        break
                except PlaywrightTimeoutError:
                    continue
        
        # 10. "Publish" 또는 "List Item" 버튼 클릭
        print(f">>> Looking for publish button...")
        
        # 최소 대기 (필요한 경우에만)
        await asyncio.sleep(0.5)
        
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


async def get_poshmark_inventory(db: Session, user: User) -> List[dict]:
    """
    Poshmark 인벤토리 조회 (closet 페이지에서 리스팅 가져오기)
    Returns: List of listing items
    """
    username, password = await get_poshmark_credentials(db, user)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            try:
                # 로그인
                login_success = await login_to_poshmark_quick(page, username, password)
                if not login_success:
                    raise PoshmarkAuthError("Login failed")
                
                # 사용자의 closet 페이지로 이동
                print(f">>> Navigating to closet page...")
                closet_url = f"https://poshmark.com/closet/{username}"
                await page.goto(closet_url, wait_until="load", timeout=20000)
                await asyncio.sleep(2)  # 페이지 로드 대기
                
                # 리스팅 아이템 추출
                print(f">>> Extracting listings from closet...")
                items = await page.evaluate("""
                    () => {
                        const items = [];
                        // Poshmark 리스팅 카드 선택자 (일반적인 구조)
                        const cards = document.querySelectorAll('[data-testid*="tile"], .tile, .listing-tile, [class*="tile"]');
                        
                        cards.forEach((card, index) => {
                            try {
                                // 제목 추출
                                const titleEl = card.querySelector('a[href*="/listing/"], [class*="title"], h3, h4');
                                const title = titleEl ? titleEl.innerText.trim() : `Item ${index + 1}`;
                                
                                // 가격 추출
                                const priceEl = card.querySelector('[class*="price"], [class*="amount"]');
                                const priceText = priceEl ? priceEl.innerText.trim() : '';
                                const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                                
                                // 이미지 URL 추출
                                const imgEl = card.querySelector('img');
                                const imageUrl = imgEl ? imgEl.src : '';
                                
                                // 링크 추출
                                const linkEl = card.querySelector('a[href*="/listing/"]');
                                const url = linkEl ? linkEl.href : '';
                                const listingId = url.match(/\\/listing\\/([^/]+)/)?.[1] || '';
                                
                                if (title && url) {
                                    items.push({
                                        title: title,
                                        price: price,
                                        imageUrl: imageUrl,
                                        url: url,
                                        listingId: listingId,
                                        sku: listingId || `poshmark-${index}`,
                                    });
                                }
                            } catch (e) {
                                console.error('Error extracting item:', e);
                            }
                        });
                        
                        return items;
                    }
                """)
                
                print(f">>> Found {len(items)} items in closet")
                return items
                
            finally:
                await browser.close()
    except PoshmarkAuthError:
        raise
    except Exception as e:
        raise PoshmarkPublishError(f"Failed to fetch inventory: {str(e)}")

