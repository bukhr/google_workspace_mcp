"""
Utility functions for Google Docs operations.

Provides helper functions for URL parsing, tab extraction, and formatting.
"""
import logging
import urllib.parse
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_tab_id_from_url(url_or_id: str) -> str:
    """
    Extract tab ID from Google Docs URL or return the ID as-is if it's already a tab ID.
    
    Args:
        url_or_id: Either a Google Docs URL with tab parameter or a direct tab ID
        
    Returns:
        str: Extracted or original tab ID
    """
    if url_or_id.startswith('http'):
        # Extract from URL: https://docs.google.com/document/d/.../edit?tab=t.xyz
        parsed = urllib.parse.urlparse(url_or_id)
        query_params = urllib.parse.parse_qs(parsed.query)
        if 'tab' in query_params:
            return query_params['tab'][0]  # Return first tab parameter
    return url_or_id  # Return as-is if not a URL


def get_tab_content_lightweight(docs_service, document_id: str, tab_id: str) -> Optional[Dict[str, Any]]:
    """
    Lightweight function to get only specific tab content without processing entire document.
    Falls back to full document processing if needed.
    
    Args:
        docs_service: Google Docs service instance
        document_id: ID of the document
        tab_id: Specific tab ID to retrieve
        
    Returns:
        Dict containing tab content and metadata, or None if failed
    """
    try:
        # First try to get just the document structure without full content
        doc_data = docs_service.documents().get(
            documentId=document_id,
            includeTabsContent=False  # Load structure only first
        ).execute()
        
        tabs = doc_data.get('tabs', [])
        target_tab = None
        
        # Find the specific tab
        for tab in tabs:
            if tab.get('tabId') == tab_id:
                target_tab = tab
                break
        
        if target_tab:
            # Now get just this tab's content
            full_doc = docs_service.documents().get(
                documentId=document_id,
                includeTabsContent=True
            ).execute()
            
            # Find and return just the target tab
            for tab in full_doc.get('tabs', []):
                if tab.get('tabId') == tab_id:
                    return {
                        'tab_data': tab,
                        'doc_title': full_doc.get('title', 'Unknown Document'),
                        'inline_objects': full_doc.get('inlineObjects', {}),
                        'timestamp': datetime.now()
                    }
        
        # Fallback: tab not found or structure loading failed
        return None
        
    except Exception as e:
        logger.warning(f"Lightweight tab loading failed: {e}, falling back to full processing")
        return None


def format_tab_selection_prompt(doc_title: str, tabs_count: int) -> str:
    """Helper function to format the tab selection prompt for users."""
    return f"""
🎯 **Listo para leer contenido de "{doc_title}"**

Encontré {tabs_count} pestañas en este documento. 

**¿Qué te gustaría que lea?**
- Proporciona el ID de la pestaña (código entre comillas invertidas como `tab_0`)
- Cargaré ese contenido y lo usaré como contexto para nuestra conversación
- También puedes especificar IDs de sub-pestañas para una lectura más enfocada

**Ejemplo:** "Lee la pestaña `tab_0`" o "Muéstrame el contenido de `child_tab_2`"
"""
