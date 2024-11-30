import os
import time
import json
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from openai import OpenAI
from pydantic import BaseModel
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Load environment variables
load_dotenv()


def get_funda_links(city: str, max_pages=3) -> list:
    options = Options()
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        base_url = "https://www.funda.nl/zoeken/koop/"
        all_links = []

        for page in range(1, max_pages + 1):
            # Construct URL with pagination
            url = f'{base_url}?selected_area=["{city}"]&search_result={page}'
            print(f"Fetching page {page}: {url}")
            driver.get(url)

            # Wait for the links to load
            links_selector = (
                By.CSS_SELECTOR,
                'a[data-test-id="object-image-link"]',
            )

            # Wait for the links to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located(links_selector)
            )

            # Extract links
            links = driver.find_elements(*links_selector)
            hrefs = [link.get_attribute("href") for link in links]
            all_links.extend(hrefs)

        return all_links
    finally:
        driver.quit()


def convert_urls_to_llm_friendly_text(
    links: list, cache_dir: str = "cache", batch_size: int = 20
):
    total_links = len(links)

    for index, link in enumerate(links):
        # Construct the reader API URL
        reader_api_url = f"https://r.jina.ai/{link}"
        print(f"[{index + 1}/{total_links}] Processing: {reader_api_url}")

        try:
            # Make the request to the reader API
            response = requests.get(reader_api_url)
            response.raise_for_status()  # Raise an error for bad responses

            # Extract the last part of the URL for the filename
            filename = link.rstrip("/").split("/")[-1] + ".md"
            file_path = os.path.join(cache_dir, filename)

            # Save the response content to a markdown file
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(response.text)

            print(f"Saved: {file_path}")

        except requests.RequestException as e:
            print(f"Failed to process {reader_api_url}: {e}")

        # Wait for a minute after every `batch_size` requests
        if (index + 1) % batch_size == 0 and index + 1 < total_links:
            print(f"Processed {batch_size} requests. Waiting for 1 minute...")
            time.sleep(60)  # Wait for 60 seconds


def extract_property_data_from_files(file_list: List[str], cache_dir="cache"):
    # Initialize the OpenAI client
    client = OpenAI()

    # Define the Pydantic models for the property data
    class Dimensions(BaseModel):
        livingArea: float  # Living area in square meters
        balconyArea: Optional[float]  # Balcony area in square meters
        externalStorage: Optional[float]  # External storage area in square meters
        volume: Optional[float]  # Property volume in cubic meters

    class Rooms(BaseModel):
        totalRooms: Optional[float]  # Total number of rooms
        bedrooms: Optional[float]  # Number of bedrooms
        bathrooms: Optional[float]  # Number of bathrooms

    class LocationDetails(BaseModel):
        neighborhood: str  # Neighborhood name

    class PriceDetails(BaseModel):
        price: float  # Listing price in euros
        pricePerSquareMeter: Optional[float]  # Price per square meter in euros

    class PropertyData(BaseModel):
        dimensions: Dimensions  # Dimensions details
        rooms: Rooms  # Rooms details
        locationDetails: LocationDetails  # Location details
        priceDetails: PriceDetails  # Price details

    for file_path in file_list:
        try:
            # Read the content of the markdown file
            with open(file_path, "r", encoding="utf-8") as file:
                file_content = file.read()

            # Send the content to the completion API
            completion = client.beta.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": "Extract the property data."},
                    {"role": "user", "content": file_content},
                ],
                response_format=PropertyData,
            )

            # Parse the response
            property_data = completion.choices[0].message.parsed
            if not property_data:
                print(f"Failed to extract data from: {file_path}")
                continue

            # Generate a JSON file name based on the original file name
            json_filename = Path(file_path).stem + ".json"
            json_file_path = Path(cache_dir) / json_filename

            # Save the extracted data as a JSON file
            with open(json_file_path, "w", encoding="utf-8") as json_file:
                json_file.write(property_data.model_dump_json(indent=2))

            print(f"Extracted data saved to: {json_file_path}")

        except Exception as e:
            print(f"Error processing file {file_path}: {e}")


def add_records_to_influxdb(
    json_files: List[str],
    influx_url="http://localhost:8086",
    token=os.getenv("INFLUXDB_TOKEN"),
    org="local-org",
    bucket="local-bucket",
):
    client = InfluxDBClient(url=influx_url, token=token, org=org)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    for file_path in json_files:
        try:
            # Load JSON file
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract fields from the JSON structure
            neighborhood = data["locationDetails"]["neighborhood"]
            living_area = data["dimensions"]["livingArea"]
            balcony_area = data["dimensions"].get("balconyArea", 0.0)
            external_storage = data["dimensions"].get("externalStorage", 0.0)
            volume = data["dimensions"].get("volume", 0.0)
            total_rooms = data["rooms"].get("totalRooms", 0.0)
            bedrooms = data["rooms"].get("bedrooms", 0.0)
            bathrooms = data["rooms"].get("bathrooms", 0.0)
            price = data["priceDetails"]["price"]
            price_per_sqm = data["priceDetails"].get("pricePerSquareMeter", 0.0)

            # Create a data point for InfluxDB
            point = (
                Point("real_estate")
                .tag("neighborhood", neighborhood)
                .field("living_area", living_area)
                .field("balcony_area", balcony_area)
                .field("external_storage", external_storage)
                .field("volume", volume)
                .field("total_rooms", total_rooms)
                .field("bedrooms", bedrooms)
                .field("bathrooms", bathrooms)
                .field("price", price)
                .field("price_per_sqm", price_per_sqm)
            )

            # Write the data point to InfluxDB
            write_api.write(bucket=bucket, org=org, record=point)
            print(f"Record added for neighborhood: {neighborhood}")

        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

    client.close()


# Make sure the cache directory exists
os.makedirs("cache", exist_ok=True)

# Get property links for Amsterdam
# links = get_funda_links("amsterdam", max_pages=3)
# print(f"Found {len(links)} links")

# Save links to a file
# open("cache/funda_links.txt", "w").write("\n".join(links))
# links = open("cache/funda_links.txt").read().splitlines()

# Convert the links to LLM-friendly text
# convert_urls_to_llm_friendly_text(links, cache_dir="cache")

# markdown_files = list(Path("cache").glob("*.md"))
# extract_property_data_from_files(markdown_files, cache_dir="cache")


# json_files = list(Path("cache").glob("*.json"))
# add_records_to_influxdb(json_files)
