from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


def fetch_html_from_funda(output_file="funda_page.html"):
    """
    Fetches the HTML content of the Funda homepage and saves it to a file.

    Args:
        output_file (str): The file to save the HTML content.
    """
    # Set up Selenium options for headless browsing
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    # Use webdriver-manager to handle ChromeDriver setup
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Navigate to the Funda website
        driver.get("https://www.funda.nl/")

        # Wait for a specific element to load (modify the selector as needed)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Wait for JavaScript-rendered content (modify as needed)
        driver.implicitly_wait(5)

        # Get the HTML content
        html_content = driver.page_source

        # Save the HTML content to a file
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(html_content)

        print(f"HTML content saved to {output_file}")
    finally:
        # Ensure the driver quits even if an error occurs
        driver.quit()


# Example usage
# fetch_html_from_funda(output_file="funda_homepage.html")
