import os
import time
import re
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from concurrent.futures import ProcessPoolExecutor
import datetime

# Load environment variables
load_dotenv()

# Configuration
LMS_URL = "https://lms.ssu.ac.kr/"
# Credentials provided by user
USER_ID = os.getenv("USER_ID")
USER_PW = os.getenv("USER_PW")

if not USER_ID or not USER_PW:
    raise ValueError("USER_ID and USER_PW must be set in .env file")

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def get_current_semester():
    now = datetime.datetime.now()
    year = now.year
    month = now.month
    
    # Simple semester logic
    # 1st Semester: Feb - July (2-7)
    # 2nd Semester: Aug - Jan (8-12, 1)
    
    if 2 <= month <= 7:
        semester = 1
    else:
        semester = 2
        if month == 1:
            year -= 1
            
    return f"{year}년 {semester}학기"

def get_courses(page):
    current_semester = get_current_semester()
    print(f"Current Semester: {current_semester}")
    print("Fetching course list...")
    
    # Navigate to 'All Courses' to get a clean list
    page.goto("https://canvas.ssu.ac.kr/courses")
    
    courses = []
    
    # Select all course rows
    rows = page.query_selector_all("tr.course-list-table-row")
    
    seen_urls = set()
    for row in rows:
        try:
            # Extract Term
            term_el = row.query_selector("td.course-list-term-column")
            if not term_el:
                continue
            term = term_el.inner_text().strip()
            
            # Filter by Semester
            if term != current_semester:
                continue
                
            # Extract Name and Link
            link_el = row.query_selector("td.course-list-course-title-column a")
            if not link_el:
                continue
                
            url = link_el.get_attribute("href")
            name_el = link_el.query_selector("span.name")
            name = name_el.inner_text().strip() if name_el else link_el.inner_text().strip()
            
            # Filter by Name Pattern (Name (Code))
            # Regex: Any text followed by space and (digits)
            if not re.search(r'.+ \(\d+\)', name):
                continue
            
            # Filter valid course URLs
            if "/courses/" in url and name and url not in seen_urls:
                # Basic filter to avoid system links
                if re.search(r'\d+', url): 
                    full_url = f"https://canvas.ssu.ac.kr{url}" if not url.startswith("http") else url
                    courses.append({"name": name, "url": full_url})
                    seen_urls.add(url)
        except Exception as e:
            print(f"Error parsing row: {e}")
            continue

    print(f"Found {len(courses)} courses for {current_semester}.")
    return courses

def process_item(page, item_url, course_dir, week_name):
    try:
        # Navigate to item
        # If item_url is relative, prepend base
        full_url = f"https://canvas.ssu.ac.kr{item_url}" if not item_url.startswith("http") else item_url
        page.goto(full_url)
        page.wait_for_load_state('networkidle')
        
        # Create week directory
        week_dir = os.path.join(course_dir, sanitize_filename(week_name))
        os.makedirs(week_dir, exist_ok=True)
        
        # Check for file downloads
        # 1. Direct download links (attachments)
        # 2. Embedded files (often in iframes or specific classes)
        
        # Common selectors for downloads in Canvas/LMS
        download_selectors = [
            "a[href*='/download']", 
            "a.file_download_btn",
            "a.instructure_file_link",
            # Add generic file extensions
            "a[href$='.zip']", "a[href$='.pdf']", "a[href$='.pptx']", "a[href$='.ppt']",
            "a[href$='.docx']", "a[href$='.doc']", "a[href$='.hwp']", "a[href$='.xlsx']", "a[href$='.xls']"
        ]
        
        found_downloads = False
        for selector in download_selectors:
            links = page.query_selector_all(selector)
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if not href: continue
                    
                    print(f"    - Found download link: {href}")
                    
                    # Start download
                    with page.expect_download(timeout=10000) as download_info:
                        link.click()
                    
                    download = download_info.value
                    filename = download.suggested_filename
                    save_path = os.path.join(week_dir, filename)
                    
                    # Handle duplicates: Skip if exists
                    if os.path.exists(save_path):
                        print(f"      -> [SKIP] File already exists: {filename}")
                        # We can optionally delete the download if we don't save it, 
                        # but Playwright manages temp files.
                        # Just don't save it to target.
                        found_downloads = True # Mark as found so we don't look for iframes unnecessarily
                        continue 
                        
                    download.save_as(save_path)
                    print(f"      -> Downloaded to: {save_path}")
                    found_downloads = True
                except Exception as e:
                    print(f"      -> Download failed: {e}")

        if not found_downloads:
            # Check for iframes that might contain content (e.g. PDF viewer)
            print("    - No direct links found. Checking for iframes...")
            # Wait a bit for frames to load content
            page.wait_for_timeout(3000)
            
            frames = page.frames
            print(f"    - Found {len(frames)} frames.")
            
            for i, frame in enumerate(frames):
                try:
                    # Check frame URL
                    frame_url = frame.url
                    # print(f"      [Frame {i}] URL: {frame_url}")
                    
                    if not frame_url: continue
                    
                    # Case A: Direct PDF in iframe
                    if frame_url.lower().endswith('.pdf'):
                        print(f"    - Found PDF in iframe: {frame_url}")
                        try:
                            # Check for duplicate before downloading (if possible to guess name)
                            # Hard to guess name from URL always, but let's try
                            guessed_name = frame_url.split('/')[-1]
                            guessed_path = os.path.join(week_dir, guessed_name)
                            if os.path.exists(guessed_path):
                                print(f"      -> [SKIP] PDF already exists (guessed): {guessed_name}")
                                found_downloads = True
                                break

                            with page.expect_download(timeout=10000) as download_info:
                                page.evaluate(f"window.open('{frame_url}')")
                            
                            download = download_info.value
                            filename = download.suggested_filename
                            save_path = os.path.join(week_dir, filename)
                            
                            # Real check after getting filename
                            if os.path.exists(save_path):
                                print(f"      -> [SKIP] File already exists: {filename}")
                                found_downloads = True
                                break

                            download.save_as(save_path)
                            print(f"      -> Downloaded iframe PDF to: {save_path}")
                            found_downloads = True
                            break
                        except Exception as e:
                            print(f"      -> Failed to download iframe PDF: {e}")

                    # Case B: Canvas DocViewer or other viewers
                    # Look for specific download buttons inside the frame
                    
                    download_selectors_frame = [
                        "#doc_viewer_download_link", 
                        "a.download_link",
                        ".vc-pctrl-download-btn", 
                        "[title*='Download']", "[title*='다운로드']",
                        "[aria-label*='Download']", "[aria-label*='다운로드']",
                        "button:has(i.fa-download)", "a:has(i.fa-download)",
                        "button:has(svg[data-icon='download'])",
                        "button[class*='download']", "a[class*='download']" # Broad class search
                    ]
                    
                    # Combine into one selector for efficient waiting
                    combined_selector = ", ".join(download_selectors_frame)
                    
                    try:
                        # Wait for ANY of the download buttons to appear
                        if frame.is_visible(combined_selector, timeout=2000):
                            print(f"      [Frame {i}] Found download button matching generic selectors!")
                            
                            # Find which one specifically (or just query the combined one)
                            download_btn = frame.query_selector(combined_selector)
                            
                            if download_btn:
                                try:
                                    with page.expect_download(timeout=10000) as download_info:
                                        download_btn.click()
                                    
                                    download = download_info.value
                                    filename = download.suggested_filename
                                    save_path = os.path.join(week_dir, filename)
                                    
                                    if os.path.exists(save_path):
                                        print(f"      -> [SKIP] File already exists: {filename}")
                                        found_downloads = True
                                        break

                                    download.save_as(save_path)
                                    print(f"      -> Downloaded file from iframe button to: {save_path}")
                                    found_downloads = True
                                    break
                                except Exception as e:
                                    print(f"      -> Failed to download from iframe button: {e}")
                    except:
                        pass

                except Exception as e:
                    pass

        if not found_downloads:
            # Debug: Take screenshot if no downloads found
            debug_dir = os.path.join("debug_screenshots", sanitize_filename(course_dir.split(os.sep)[-1]))
            os.makedirs(debug_dir, exist_ok=True)
            screenshot_path = os.path.join(debug_dir, f"{sanitize_filename(week_name)}_{sanitize_filename(item_url.split('/')[-1])}.png")
            try:
                page.screenshot(path=screenshot_path)
                print(f"    [DEBUG] No downloads found. Saved screenshot to: {screenshot_path}")
            except:
                pass

    except Exception as e:
        print(f"  - Error processing item {item_url}: {e}")

def process_course(page, course):
    print(f"Processing: {course['name']}")
    course_dir = os.path.join("downloads", sanitize_filename(course['name']))
    os.makedirs(course_dir, exist_ok=True)
    
    try:
        page.goto(course['url'])
        
        # Find "Weekly Learning" or "Lecture Contents"
        target_link = None
        for text in ["주차학습", "강의콘텐츠", "Modules", "강의자료"]:
            try:
                if page.get_by_text(text, exact=True).count() > 0:
                    target_link = page.get_by_text(text, exact=True).first
                    break
            except:
                continue
        
        if not target_link:
            print(f"Could not find 'Weekly Learning' link for {course['name']}. Skipping.")
            # Debug screenshot
            os.makedirs("debug_screenshots", exist_ok=True)
            page.screenshot(path=f"debug_screenshots/{sanitize_filename(course['name'])}_no_link.png")
            return

        print(f"Found link: {target_link.inner_text()}")
        target_link.click()
        
        # Handle LTI Iframe (tool_content)
        # Many courses use an external tool for modules
        working_frame = page
        try:
            # Wait a bit for iframe to potentially load
            page.wait_for_timeout(2000)
            
            frame = page.frame(name="tool_content")
            if frame:
                print(f"Found 'tool_content' iframe. Switching context.")
                working_frame = frame
                working_frame.wait_for_selector("div[aria-label*='주차']", timeout=15000)
            else:
                print("No 'tool_content' iframe found. Using main page.")
                # Relaxed wait - just wait for load
                page.wait_for_load_state('networkidle')
        except Exception as e:
            print(f"Error waiting for module content: {e}")
            # Continue anyway, might be non-standard structure

        # Expand All
        print("Attempting to 'Expand All'...")
        expand_selectors = [
            "button.xnmb-all_fold-btn", 
            "button.xncb-fold-toggle-button",
            "button:has-text('모두 펼치기')",
            "button:has-text('모든 주차 펴기')"
        ]
        
        expand_clicked = False
        for selector in expand_selectors:
            if working_frame.is_visible(selector):
                print(f"Found expand button: {selector}")
                working_frame.click(selector)
                expand_clicked = True
                working_frame.wait_for_timeout(2000)
                break
        
        if not expand_clicked:
            print("Trying individual expansion...")
            try:
                # Click headers by aria-label (e.g. "1주차", "2주차"...)
                headers = working_frame.query_selector_all("div[aria-label*='주차']")
                for header in headers:
                    try:
                        # Check for collapsed icon (caret-right)
                        if header.query_selector("i.fa-caret-right") or header.query_selector("i.icon-solid.fa-caret-right"):
                            header.click()
                            working_frame.wait_for_timeout(200)
                    except:
                        pass
                working_frame.wait_for_timeout(1000)
            except Exception as e:
                print(f"Error expanding modules: {e}")

        # Extract Module Items with Week Context
        # We iterate through headers and items in document order
        print("Scanning modules and items...")
        
        # Selector for both headers and items
        # Header: div.xnmb-module-left-wrapper (contains text like "1주차")
        # Item: a.xnmb-module_item-left-title
        elements = working_frame.query_selector_all("div.xnmb-module-left-wrapper, a.xnmb-module_item-left-title")
        
        current_week = "Unknown_Week"
        items_to_process = []
        
        for element in elements:
            try:
                # Check if it's a header
                class_attr = element.get_attribute("class")
                if "xnmb-module-left-wrapper" in class_attr:
                    # It's a header
                    # Try to get text from aria-label or inner text
                    aria_label = element.get_attribute("aria-label")
                    if aria_label:
                        current_week = aria_label.strip()
                    else:
                        # Fallback to inner text, taking first line
                        text = element.inner_text().strip()
                        if text:
                            current_week = text.splitlines()[0].strip()
                    # print(f"  [Week] {current_week}")
                    
                elif "xnmb-module_item-left-title" in class_attr:
                    # It's an item
                    item_name = element.inner_text().strip()
                    item_url = element.get_attribute("href")
                    
                    if item_url:
                        items_to_process.append({
                            "name": item_name,
                            "url": item_url,
                            "week": current_week
                        })
            except Exception as e:
                print(f"Error scanning element: {e}")
        
        print(f"Found {len(items_to_process)} items to process.")
        
        if len(items_to_process) == 0:
             # Debug screenshot for empty course
            os.makedirs("debug_screenshots", exist_ok=True)
            page.screenshot(path=f"debug_screenshots/{sanitize_filename(course['name'])}_no_items.png")
        
        # Process items
        for item in items_to_process:
            print(f"Processing: [{item['week']}] {item['name']}")
            process_item(page, item['url'], course_dir, item['week'])

    except Exception as e:
        print(f"Error processing course {course['name']}: {e}")

def process_course_task(course, storage_state):
    """
    Worker function to process a single course in a separate process.
    """
    print(f"[Worker] Starting processing for: {course['name']}")
    with sync_playwright() as p:
        # Launch a new browser instance for this worker
        browser = p.chromium.launch(headless=False)
        # Create context with the shared storage state (cookies)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        
        try:
            process_course(page, course)
        except Exception as e:
            print(f"[Worker] Error in course {course['name']}: {e}")
        finally:
            browser.close()
    print(f"[Worker] Finished processing for: {course['name']}")

def run():
    with sync_playwright() as p:
        print("Launching main browser for login...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 1. Login
        print("Logging in...")
        page.goto(LMS_URL)
        
        # Handle popup if exists
        try:
            page.click("text=닫기", timeout=2000)
        except:
            pass

        # Click login button
        print("Clicking '통합 로그인'...")
        try:
            if page.is_visible("a.xn-sso-login-btn"):
                page.click("a.xn-sso-login-btn")
            else:
                page.click("text=통합 로그인")
            
            # Wait for login page
            page.wait_for_selector("#userid", timeout=10000)
        except:
            pass 

        page.fill("#userid", USER_ID)
        page.fill("#pwd", USER_PW)
        
        # Click login submit
        try:
            page.click("a.btn_login", timeout=5000)
        except:
            page.click("text=로그인")
        
        # Wait for login to complete
        page.wait_for_load_state('networkidle')
        
        # Handle popup again after login
        try:
            page.click("text=닫기", timeout=3000)
        except:
            pass

        # 2. Get Course List
        courses = get_courses(page)
        
        # 3. Save Storage State (Cookies)
        # We save it to a temporary file or just keep it in memory if possible.
        # storage_state() returns a dict, which is picklable and can be passed to workers.
        storage_state = context.storage_state()
        
        print("Login successful and courses fetched. Closing main browser.")
        browser.close()

    # Print download location
    download_root = os.path.abspath("downloads")
    print(f"\n[INFO] Files will be downloaded to: {download_root}\n")
    
    # 4. Process Courses Concurrently
    # Adjust max_workers as needed. 
    # User requested one worker per course
    max_workers = len(courses)
    if max_workers == 0:
        print("No courses to process.")
        return

    print(f"Starting {max_workers} worker processes...")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_course_task, course, storage_state) for course in courses]
        
        # Wait for all to complete
        for future in futures:
            try:
                future.result()
            except Exception as e:
                print(f"A worker failed: {e}")

    print("All done!")

if __name__ == "__main__":
    run()
