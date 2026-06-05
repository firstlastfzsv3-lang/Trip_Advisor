# scraper/scraper.py — Production scraper with resolved URL
import requests
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.getenv("API_KEY", "ok_8f0f635b78a6f2700f0e0b30ddad1a3c")
BASE_URL = "https://tripadvisor-scraper-api.omkar.cloud/tripadvisor/reviews"

# Use the resolved TripAdvisor URL directly
QUERY = "https://www.tripadvisor.com/Attraction_Review-g293890-d310712-Reviews-Pashupatinath_Temple-Kathmandu_Kathmandu_Valley_Bagmati_Zone_Central_Region.html"

OUTPUT_DIR = "raw_reviews"
CHECKPOINT_FILE = "checkpoint.json"

def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")

def fetch_page(page, max_retries=3):
    params = {
        "query": QUERY,
        "page": page,
        "sort_by": "most_recent",
        "locale": "en-US"
    }
    headers = {"API-Key": API_KEY}

    for attempt in range(max_retries):
        try:
            resp = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            try:
                error_body = e.response.json()
                log(f"Page {page} HTTP {e.response.status_code}: {error_body}")
            except:
                log(f"Page {page} HTTP {e.response.status_code}: {e.response.text[:500]}")

            if e.response.status_code == 400:
                raise Exception(f"Page {page} failed with 400 Bad Request: {e.response.text[:500]}")

            wait = 2 ** attempt
            log(f"Page {page} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            log(f"Page {page} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)

    raise Exception(f"Page {page} failed after {max_retries} retries")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"last_page": 0, "run_id": None}

def save_checkpoint(page, run_id):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"last_page": page, "run_id": run_id}, f)

def scrape():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    checkpoint = load_checkpoint()
    start_page = checkpoint["last_page"] + 1
    run_id = checkpoint["run_id"] or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    scraped_at = datetime.now(timezone.utc).isoformat()

    log(f"Starting run {run_id} from page {start_page}")

    page = start_page
    total_pages = None
    all_reviews = []

    while True:
        data = fetch_page(page)
        reviews = data.get("results", [])

        page_file = f"{OUTPUT_DIR}/page_{page:04d}_{run_id}.json"
        with open(page_file, "w", encoding="utf-8") as f:
            json.dump({
                "scraped_at": scraped_at,
                "run_id": run_id,
                "page": page,
                "api_response": data
            }, f, ensure_ascii=False)

        all_reviews.extend(reviews)
        save_checkpoint(page, run_id)

        if total_pages is None:
            total_pages = data.get("total_pages", page)
            log(f"Total pages: {total_pages}")

        log(f"Page {page}: {len(reviews)} reviews | total: {len(all_reviews)}")

        if page >= total_pages or not data.get("next"):
            break

        page += 1
        time.sleep(0.5)

    jsonl_file = f"{OUTPUT_DIR}/reviews_{run_id}.jsonl"
    with open(jsonl_file, "w", encoding="utf-8") as f:
        for r in all_reviews:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "run_id": run_id,
        "scraped_at": scraped_at,
        "total_pages": page,
        "total_reviews": len(all_reviews),
        "jsonl_file": jsonl_file,
        "query": QUERY
    }
    with open(f"{OUTPUT_DIR}/manifest_{run_id}.json", "w") as f:
        json.dump(manifest, f, indent=2)

    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    log(f"✓ Complete. {len(all_reviews)} reviews → {jsonl_file}")
    return manifest

if __name__ == "__main__":
    scrape()