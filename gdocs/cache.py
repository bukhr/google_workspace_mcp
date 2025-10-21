"""
Document caching module for Google Docs.

Provides caching functionality to reduce API calls and improve performance.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global cache for document content
# Structure: {document_id: {"content": processed_content, "timestamp": datetime, "tabs_data": dict}}
_document_cache: Dict[str, Dict[str, Any]] = {}
_cache_ttl_minutes = 30  # Time to live for cached documents


def is_cache_valid(document_id: str) -> bool:
    """Check if cached document data is still valid."""
    if document_id not in _document_cache:
        return False
    
    cached_time = _document_cache[document_id].get("timestamp")
    if not cached_time:
        return False
    
    return datetime.now() - cached_time < timedelta(minutes=_cache_ttl_minutes)


def get_cached_document(document_id: str) -> Optional[Dict[str, Any]]:
    """Get cached document data if valid."""
    if is_cache_valid(document_id):
        return _document_cache[document_id]
    return None


def cache_document(document_id: str, content: str, tabs_data: Dict[str, Any]) -> None:
    """Cache processed document content and tabs data."""
    _document_cache[document_id] = {
        "content": content,
        "tabs_data": tabs_data,
        "timestamp": datetime.now()
    }
    logger.info(f"Cached document {document_id}")


def clear_cache(document_id: str) -> None:
    """Clear cache for a specific document."""
    if document_id in _document_cache:
        del _document_cache[document_id]
        logger.info(f"Cleared cache for document {document_id}")
