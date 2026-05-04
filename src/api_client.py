import logging
from typing import Dict, List

import requests

from .offline_data import FALLBACK_POSTS

logger = logging.getLogger(__name__)

API_URL = "https://jsonplaceholder.typicode.com/posts"


def fetch_posts(limit: int = 10) -> List[Dict]:
    """
    Fetch posts from JSONPlaceholder API.
    Falls back to bundled offline data if the network is unavailable.
    """
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        posts = response.json()[:limit]
        logger.info(f"Fetched {len(posts)} posts from API")
        return posts
    except requests.RequestException as e:
        logger.warning(f"API unavailable ({e}) — using offline fallback data")
        return FALLBACK_POSTS[:limit]


def format_post(post: Dict) -> str:
    return f"Title: {post['title']}\n\n{post['body']}"


def validate_post(post: Dict) -> bool:
    return all(k in post for k in ("id", "title", "body"))
