# scraper/clean_and_upload.py
"""
Converts raw TripAdvisor API JSONL into cleaned research dataset
and uploads directly to Supabase PostgreSQL.

Based on: raw_json_to_csv.py (LLM-SC project)
"""

import os
import json
import re
import unicodedata
import logging
from pathlib import Path
from datetime import datetime

from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# ── Sacred-content keyword dictionaries ──────────────────────────────────────
SACRED_TERMS = {
    "has_ritual": [
        "aarti", "aarati", "puja", "cremation", "darshan",
        "parikrama", "tarpan", "ceremony", "ritual",
        "chanting", "offerings", "prayer",
    ],
    "has_actor": [
        "sadhu", "sadhus", "priest", "pilgrim",
        "devotee", "monk", "yogi",
    ],
    "has_space": [
        "ghat", "ghats", "bagmati", "lingam",
        "sanctum", "pagoda", "riverbank",
    ],
    "has_spiritual": [
        "sacred", "spiritual", "profound", "moksha",
        "awe", "blessed", "devotion", "reverence",
    ],
    "has_festival": [
        "shivaratri", "shivratri", "teej", "festival", "aarati",
    ],
    "has_rule": [
        "non-hindu", "restricted", "not allowed", "entry fee", "forbidden",
    ],
}


# ── Step 1 : extract reviews from JSONL ────────────────────────────────────
def extract_reviews(jsonl_path: str) -> list[dict]:
    log.info(f"Loading: {jsonl_path}")
    reviews = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                reviews.append(json.loads(line))
    log.info(f"Raw reviews extracted: {len(reviews)}")
    return reviews


# ── Step 2 : flatten nested fields ─────────────────────────────────────────
def flatten_fields(review: dict) -> dict:
    trip = review.get("trip", {}) or {}
    reviewer = review.get("reviewer", {}) or {}
    images = review.get("images", []) or []

    return {
        "trip_type": trip.get("trip_type", "unknown") if isinstance(trip, dict) else "unknown",
        "stay_date": trip.get("stay_date", "") if isinstance(trip, dict) else "",
        "reviewer_name": reviewer.get("name", "") if isinstance(reviewer, dict) else "",
        "image_count": len(images) if isinstance(images, list) else 0,
        "has_images": len(images) > 0 if isinstance(images, list) else False,
        "image_urls": "|".join(images) if isinstance(images, list) and images else "",
    }


# ── Step 3 : parse dates ───────────────────────────────────────────────────
def parse_dates(review: dict) -> dict:
    pub_date = review.get("published_at_date", "")
    date_obj = None
    year = None
    month = None
    quarter = None

    if pub_date and "-" in str(pub_date):
        try:
            date_obj = datetime.strptime(pub_date, "%Y-%m-%d")
            year = date_obj.year
            month = date_obj.month
            quarter = (month - 1) // 3 + 1
        except ValueError:
            pass

    return {
        "date": pub_date,
        "year": year,
        "month": month,
        "quarter": quarter,
    }


# ── Step 4 : COVID-period labels ─────────────────────────────────────────────
def add_period(year: int) -> str:
    if year is None:
        return "unknown"
    if year == 2019:      return "pre_covid_peak"
    elif year == 2020:    return "covid_onset"
    elif year == 2021:    return "covid_deep"
    elif year == 2022:    return "recovery_early"
    elif year == 2023:    return "recovery_late"
    elif year >= 2024:    return "post_recovery"
    elif year < 2015:     return "early_period"
    else:                 return "growth_period"


# ── Step 5 : minimum-intervention text cleaning ────────────────────────────
def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"&[a-z]+;|&#\d+;", " ", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Step 6 : sentiment class from star rating ───────────────────────────────
def sentiment_class(rating) -> str:
    if rating is None:
        return "unknown"
    if rating >= 4:   return "positive"
    elif rating == 3: return "neutral"
    else:             return "negative"


# ── Step 7 : reviewer-type proxy ────────────────────────────────────────────
def reviewer_type(trip_type: str) -> str:
    if trip_type == "family":  return "likely_pilgrim"
    elif trip_type == "solo":  return "mixed"
    else:                      return "likely_tourist"


# ── Step 8 : sacred-content flags ─────────────────────────────────────────────
def add_sacred_flags(text_clean: str) -> dict:
    text_lower = text_clean.lower() if text_clean else ""
    flags = {}
    for flag, terms in SACRED_TERMS.items():
        flags[flag] = any(term in text_lower for term in terms)
    flags["has_sacred_content"] = any(flags.values())
    return flags


# ── Step 9 : deduplicate & filter ────────────────────────────────────────────
def deduplicate_and_filter(records: list[dict]) -> list[dict]:
    before = len(records)

    # Remove duplicate review_ids (keep first)
    seen_ids = set()
    unique = []
    for r in records:
        rid = r.get("review_id")
        if rid not in seen_ids:
            seen_ids.add(rid)
            unique.append(r)

    # Remove duplicate texts
    seen_texts = set()
    unique2 = []
    for r in unique:
        text = r.get("text_clean", "")
        if text not in seen_texts:
            seen_texts.add(text)
            unique2.append(r)

    # Remove reviews shorter than 8 words
    filtered = [r for r in unique2 if r.get("word_count", 0) >= 8]

    after = len(filtered)
    log.info(f"Dedup + filter: {before} → {after} (removed {before - after})")
    return filtered


# ── Main pipeline ─────────────────────────────────────────────────────────────
def process_and_upload():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Find latest JSONL
    jsonl_files = list(Path("raw_reviews").glob("reviews_*.jsonl"))
    if not jsonl_files:
        raise Exception("No JSONL file found in raw_reviews/")

    jsonl_file = jsonl_files[0]
    run_id = jsonl_file.stem.replace("reviews_", "")

    # Extract
    reviews = extract_reviews(str(jsonl_file))

    # Transform each review
    records = []
    for review in reviews:
        # Flatten
        flat = flatten_fields(review)
        dates = parse_dates(review)

        # Clean text
        title_clean = clean_text(review.get("title", ""))
        text_clean = clean_text(review.get("text", ""))
        word_count = len(text_clean.split()) if text_clean else 0

        # Skip if too short (will filter later, but pre-check)
        if word_count < 8:
            continue

        # Sentiment
        rating = review.get("rating")
        sentiment = sentiment_class(rating)

        # Reviewer type
        trip_type = flat["trip_type"]
        rev_type = reviewer_type(trip_type)

        # Period
        year = dates["year"]
        period = add_period(year)

        # Sacred flags
        sacred = add_sacred_flags(text_clean)

        record = {
            "review_id": review.get("review_id"),
            "title_clean": title_clean,
            "text_clean": text_clean,
            "rating": rating,
            "sentiment_class": sentiment,
            "date": dates["date"],
            "year": year,
            "month": dates["month"],
            "quarter": dates["quarter"],
            "period": period,
            "trip_type": trip_type,
            "reviewer_type": rev_type,
            "reviewer_name": flat["reviewer_name"],
            "word_count": word_count,
            "like_count": review.get("like_count", 0),
            "has_images": flat["has_images"],
            "image_count": flat["image_count"],
            "image_urls": flat["image_urls"],
            "has_sacred_content": sacred["has_sacred_content"],
            "has_ritual": sacred["has_ritual"],
            "has_actor": sacred["has_actor"],
            "has_space": sacred["has_space"],
            "has_spiritual": sacred["has_spiritual"],
            "has_festival": sacred["has_festival"],
            "has_rule": sacred["has_rule"],
            "language": review.get("language", "en"),
            "is_translated": review.get("is_translated", False),
            "original_language": review.get("original_language", "en"),
            "review_link": review.get("review_link", ""),
            "run_id": run_id,
            "ingested_at": datetime.now().isoformat(),
        }
        records.append(record)

    # Deduplicate & filter
    records = deduplicate_and_filter(records)

    log.info(f"Final records to upload: {len(records)}")

    # Batch insert into Supabase
    BATCH_SIZE = 100
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        supabase.table("cleaned_reviews").insert(batch).execute()
        log.info(f"  Uploaded batch {i//BATCH_SIZE + 1}/{(len(records)-1)//BATCH_SIZE + 1}")

    log.info(f"✓ Uploaded {len(records)} cleaned reviews to Supabase")

    # Log run metadata
    supabase.table("scrape_runs").insert({
        "run_id": run_id,
        "run_date": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "total_reviews": len(records),
        "total_pages": len(list(Path("raw_reviews").glob("page_*.json"))),
        "storage_path": "supabase_postgresql_table",
        "scraped_at": datetime.now().isoformat(),
    }).execute()

    return len(records)


if __name__ == "__main__":
    process_and_upload()