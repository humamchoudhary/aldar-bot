import time
import random
import os
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

import re


def scrape_web(url, cookies=None, headers=None, timeout=30, rotate_user_agents=True, random_delay=True):
    """
    Scrape a website using Selenium and return only the main content text.

    Args:
        url (str): The URL to scrape
        cookies (dict, optional): Dictionary of cookies to use for authentication
        headers (dict, optional): Dictionary of headers to send with the request
        timeout (int, optional): Request timeout in seconds
        rotate_user_agents (bool, optional): Whether to use a randomized user agent
        random_delay (bool, optional): Whether to add a random delay before request

    Returns:
        dict: A dictionary containing:
            - 'status': HTTP status code
            - 'soup': BeautifulSoup object for HTML parsing
            - 'text': Clean main content text
            - 'url': Final URL after any redirects
    """
    driver = None
    try:
        # Add random delay to mimic human behavior
        if random_delay:
            time.sleep(random.uniform(1, 3))

        # Common user agents to rotate through
        common_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ]

        # Set up Chrome options
        chrome_options = Options()

        # Not using headless mode as requested
        chrome_options.add_argument("--headless")

        # Apply user agent rotation if enabled
        if rotate_user_agents:
            user_agent = random.choice(common_user_agents)
            chrome_options.add_argument(f'user-agent={user_agent}')

        # Add custom headers if provided
        if headers:
            for key, value in headers.items():
                chrome_options.add_argument(f'--header={key}: {value}')

        # Initialize the Chrome driver
        driver = webdriver.Chrome(service=Service(
            ChromeDriverManager().install()), options=chrome_options)

        # Set page load timeout
        driver.set_page_load_timeout(timeout)

        # Navigate to the URL

        url = url if url.startswith(
            ("http://", "https://")) else "https://" + url
        driver.get(url)

        # Add cookies if provided
        if cookies:
            for cookie_name, cookie_value in cookies.items():
                driver.add_cookie({'name': cookie_name, 'value': cookie_value})
            # Refresh the page to apply cookies
            driver.refresh()

        # Wait for page to fully load
        time.sleep(3)  # Additional wait to ensure JS content loads
        # print('scraping')

        # Check for and handle common cookie consent popups
        try:
            # Common cookie consent button patterns (expand this list as needed)
            cookie_button_patterns = [
                "//button[contains(., 'Accept') or contains(., 'accept') or contains(., 'Allow')]",
                "//button[contains(., 'Cookie') or contains(., 'cookie')]",
                "//a[contains(., 'Accept') or contains(., 'accept') or contains(., 'Allow')]",
                "//div[contains(@class, 'cookie') and (contains(., 'Accept') or contains(., 'accept'))]",
                "//div[contains(@id, 'cookie') and (contains(., 'Accept') or contains(., 'accept'))]",
                "//button[contains(@class, 'consent')]",
                "//button[contains(@id, 'consent')]"
            ]

            for xpath in cookie_button_patterns:
                try:
                    cookie_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    cookie_button.click()
                    time.sleep(1)  # Wait for popup to close
                    break  # Exit once we've successfully clicked a button
                except (TimeoutException, NoSuchElementException):
                    continue  # Try the next pattern
        except Exception as e:
            # If we can't handle the cookie popup, just continue with the page
            pass

        # Get the page source after potential cookie handling
        page_source = driver.page_source
        current_url = driver.current_url

        # Create BeautifulSoup object to parse the HTML
        soup = BeautifulSoup(page_source, 'html.parser')

        # Remove headers, footers, navigation, and other non-content elements
        non_content_elements = [
            "header", "footer", "nav", "sidebar",
            "aside", "menu", "comments", "comment"
        ]

        for element_name in non_content_elements:
            for element in soup.find_all(['div', 'section', 'nav', 'header', 'footer'],
                                         class_=lambda x: x and element_name in x.lower()):
                element.decompose()

            for element in soup.find_all(['div', 'section', 'nav', 'header', 'footer'],
                                         id=lambda x: x and element_name in x.lower()):
                element.decompose()

            # Direct tag removal
            for element in soup.find_all(element_name):
                element.decompose()

        # Also remove common ad-related elements
        # for element in soup.find_all(['div', 'section', 'aside'],
        #                              class_=lambda x: x and ('ad' in x.lower() or 'banner' in x.lower())):
        #     element.decompose()

        # Try to identify the main content (this is a simple heuristic)
        main_content = None

        # First look for semantic elements
        for tag in ['main', 'article', 'section']:
            if soup.find(tag):
                main_content = soup.find(tag)
                # break

        # If no semantic tags found, look for common content class/id patterns
        if not main_content:
            content_patterns = ['content', 'main',
                                'post', 'article', 'entry', 'body']
            for pattern in content_patterns:
                for element in soup.find_all(['div', 'section'],
                                             class_=lambda x: x and pattern in x.lower()):
                    if element.text.strip():  # Make sure there's content
                        main_content = element
                        break

                if not main_content:
                    for element in soup.find_all(['div', 'section'],
                                                 id=lambda x: x and pattern in x.lower()):
                        if element.text.strip():  # Make sure there's content
                            main_content = element
                            break

                if main_content:
                    break

        # If we found a main content area, use it; otherwise use the entire body
        clean_text = main_content.get_text(
            separator=' ', strip=True) if main_content else soup.get_text(separator=' ', strip=True)

        # Clean up extra whitespace
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        # print(type(clean_text))
        # print(len(clean_text.split()))

        if len(clean_text.split()) < 500:
            # print('LESS TEXT')
            content_patterns = ['content', 'main',
                                'post', 'article', 'entry', 'body']
            for pattern in content_patterns:
                for element in soup.find_all(['div', 'section'],
                                             class_=lambda x: x and pattern in x.lower()):
                    if element.text.strip():  # Make sure there's content
                        main_content = element
                        break

                if not main_content:
                    for element in soup.find_all(['div', 'section'],
                                                 id=lambda x: x and pattern in x.lower()):
                        if element.text.strip():  # Make sure there's content
                            main_content = element
                            break

                if main_content:
                    break

            # If we found a main content area, use it; otherwise use the entire body
            clean_text = main_content.get_text(
                separator=' ', strip=True) if main_content else soup.get_text(separator=' ', strip=True)

            # Clean up extra whitespace
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        else:
            print('Not Less')

        # Close the driver
        driver.quit()

        # Return results in same format as original function
        return {
            'status': 200,  # Assuming success since we got this far
            'soup': soup,
            'rtext': page_source,  # Raw HTML
            'text': clean_text,    # Clean main body text
            'url': current_url,    # Final URL after any redirects
        }

    except Exception as e:
        if driver:
            driver.quit()
        raise Exception(f"Failed to scrape {url}: {str(e)}")


if __name__ == '__main__':
    # Load existing cookies from authenticated session
    # user_cookies = {
    #     'session_id': 'abc123xyz789',
    #     'auth_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    # }

    # hti = Html2Image(output_path="temp")
    result = scrape_web(
        "https://www.go-globe.com/erp-software.php",
        # cookies=user_cookies,
        rotate_user_agents=True,
        random_delay=True
    )

    # updated_cookies = result['cookies']
    # # print("\n".join(line.strip() for line in result['text'].splitlines() if line.strip()))
    lines = str(result['text'])
    import re
    lines = re.sub(r"\s+", " ", lines).strip()
    # print(lines)
    # with open('output.txt', 'w') as file:
    #     file.writelines(lines)
    # hti.screenshot(html_str=result[''], save_as="output.png")
