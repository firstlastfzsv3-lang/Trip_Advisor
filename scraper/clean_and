# scraper/clean_and_upload.py
import os
import json
import re
from datetime import datetime
from pathlib import Path
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def clean_text(text):
    """Basic text cleaning"""
    if not text:
        return ""
    # Remove extra whitespace, keep newlines as spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def classify_sentiment(rating):
    """Rule-based sentiment from rating"""
    if rating >= 4:
        return "positive"
    elif rating == 3:
        return "neutral"
    else:
        return "negative"

def get_year_group(year):
    """Bucket year into era"""
    if year <= 2012:
        return "early"
    elif year <= 2016:
        return "growth"
    elif year <= 2020:
        return "peak"
    else:
        return "recent"

def get_reviewer_type(contribution_count):
    """Classify reviewer by activity"""
    if not contribution_count:
        return "new"
    elif contribution_count < 10:
        return "casual"
    elif contribution_count < 50:
        return "regular"
    else:
        return "expert"

def has_sacred_keywords(text):
    """Simple keyword detection for sacred/religious content"""
    if not text:
        return False
    sacred_words = ['shiva', 'hindu', 'temple', 'prayer', 'ritual', 'cremation',
                    'ghat', 'pashupatinath', 'god', 'worship', 'holy', 'sacred',
                    'blessing', 'aarti', 'puja', 'darshan', 'spiritual']
    text_lower = text.lower()
    return any(word in text_lower for word in sacred_words)

def process_reviews():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Find latest JSONL
    jsonl_files = list(Path("raw_reviews").glob("reviews_*.jsonl"))
    if not jsonl_files:
        raise Exception("No JSONL file found")

    jsonl_file = jsonl_files[0]
    run_id = jsonl_file.stem.replace("reviews_", "")

    # Read raw reviews
    reviews = []
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                reviews.append(json.loads(line))

    print(f"Processing {len(reviews)} raw reviews...")

    # Clean and transform
    cleaned = []
    for r in reviews:
        # Extract year from published_at_date
        pub_date = r.get("published_at_date", "")
        year = int(pub_date.split("-")[0]) if pub_date and "-" in str(pub_date) else None

        # Extract trip type
        trip = r.get("trip", {}) or {}
        trip_type = trip.get("trip_type", "unknown")

        # Extract reviewer info
        reviewer = r.get("reviewer", {}) or {}
        contribution_count = reviewer.get("contribution_count", 0)

        # Clean text
        raw_text = r.get("text", "") or ""
        text_clean = clean_text(raw_text)

        record = {
            "review_id": r.get("review_id"),
            "title": r.get("title", ""),
            "text_clean": text_clean,
            "rating": r.get("rating"),
            "sentiment_class": classify_sentiment(r.get("rating", 3)),
            "year": year,
            "year_group": get_year_group(year) if year else None,
            "trip_type": trip_type,
            "travel_date": trip.get("stay_date"),
            "reviewer_type": get_reviewer_type(contribution_count),
            "reviewer_contributions": contribution_count,
            "reviewer_name": reviewer.get("name"),
            "reviewer_username": reviewer.get("username"),
            "reviewer_verified": reviewer.get("is_verified", False),
            "word_count": len(text_clean.split()) if text_clean else 0,
            "has_sacred_content": has_sacred_keywords(text_clean),
            "like_count": r.get("like_count", 0),
            "language": r.get("language", "en"),
            "is_translated": r.get("is_translated", False),
            "published_at_date": pub_date,
            "review_url": r.get("review_link"),
            "run_id": run_id,
            "ingested_at": datetime.now().isoformat()
        }
        cleaned.append(record)

    print(f"Cleaned {len(cleaned)} records")

    # Create table if not exists (you'll run this SQL once in Supabase)
    # Then insert data

    # Clear old data for this run (optional) or just insert
    # Insert in batches
    BATCH_SIZE = 100
    for i in range(0, len(cleaned), BATCH_SIZE):
        batch = cleaned[i:i+BATCH_SIZE]
        supabase.table("cleaned_reviews").insert(batch).execute()
        print(f"  Inserted batch {i//BATCH_SIZE + 1}/{(len(cleaned)-1)//BATCH_SIZE + 1}")

    print(f"✓ Uploaded {len(cleaned)} cleaned reviews to Supabase")
    return len(cleaned)

if __name__ == "__main__":
    process_reviews()