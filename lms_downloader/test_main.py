import os
import pytest
from unittest.mock import patch, MagicMock
from main import sanitize_filename, run

def test_sanitize_filename():
    assert sanitize_filename("hello:world") == "helloworld"
    assert sanitize_filename("test/file") == "testfile"
    assert sanitize_filename("clean_name") == "clean_name"

def test_env_vars_loaded():
    # This test assumes .env is present and loaded by main.py
    # Since we import main, it runs the top-level code which loads .env
    from main import USER_ID, USER_PW
    assert USER_ID is not None
    assert USER_PW is not None

@patch('main.sync_playwright')
def test_run_mocked(mock_playwright):
    # Mock the entire playwright context manager and browser flow
    mock_context_manager = MagicMock()
    mock_playwright.return_value = mock_context_manager
    mock_context_manager.__enter__.return_value = mock_context_manager
    
    mock_browser = MagicMock()
    mock_context_manager.chromium.launch.return_value = mock_browser
    
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    
    mock_page = MagicMock()
    mock_context.new_page.return_value = mock_page
    
    # Mock course list finding
    # We need to simulate the page.query_selector_all return values
    # This is complex because the code iterates over them.
    # For a simple "smoke test", we can just ensure it calls login
    
    run()
    
    # Verify login flow was attempted
    # Check if page.goto was called with LMS_URL
    from main import LMS_URL, USER_ID
    
    # Verify initial navigation
    mock_page.goto.assert_any_call(LMS_URL)
    
    # Verify login inputs were filled
    mock_page.fill.assert_any_call("#userid", USER_ID)
    mock_page.fill.assert_any_call("#pwd", os.getenv("USER_PW"))
    
    # Verify login click
    # We check if either the specific selector or text was clicked
    # Since we use try-except in main, it might try both or one.
    # Let's just check if *some* click happened that looks like login
    assert mock_page.click.call_count >= 1

def test_get_courses():
    from main import get_courses, get_current_semester
    
    mock_page = MagicMock()
    
    # Mock the course rows
    # We need to create mock objects for rows, and then for elements inside them
    
    # Helper to create a mock row
    def create_mock_row(term_text, name_text, url_text):
        row = MagicMock()
        
        # Mock Term
        term_el = MagicMock()
        term_el.inner_text.return_value = term_text
        row.query_selector.side_effect = lambda selector: term_el if "term" in selector else link_el
        
        # Mock Link/Name
        link_el = MagicMock()
        link_el.get_attribute.return_value = url_text
        
        name_el = MagicMock()
        name_el.inner_text.return_value = name_text
        
        # When query_selector is called on link_el to find span.name
        link_el.query_selector.return_value = name_el
        
        return row

    current_sem = get_current_semester() # e.g. "2025년 2학기"
    
    # Row 1: Valid (Current Semester, Valid Name)
    row1 = create_mock_row(current_sem, "Python Programming (12345)", "/courses/101")
    
    # Row 2: Wrong Semester
    row2 = create_mock_row("2020년 1학기", "Old Course (67890)", "/courses/102")
    
    # Row 3: Wrong Name Format (No Code)
    row3 = create_mock_row(current_sem, "General Orientation", "/courses/103")
    
    # Row 4: Valid (Current Semester, Valid Name)
    row4 = create_mock_row(current_sem, "Data Structures (54321)", "/courses/104")
    
    mock_page.query_selector_all.return_value = [row1, row2, row3, row4]
    
    courses = get_courses(mock_page)
    
    # Verify navigation
    mock_page.goto.assert_called_with("https://canvas.ssu.ac.kr/courses")
    
    # Verify results
    assert len(courses) == 2
    
    assert courses[0]['name'] == "Python Programming (12345)"
    assert courses[0]['url'] == "https://canvas.ssu.ac.kr/courses/101"
    
    assert courses[1]['name'] == "Data Structures (54321)"
    assert courses[1]['url'] == "https://canvas.ssu.ac.kr/courses/104"

