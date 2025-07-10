"""
Google Docs MCP Tools

This module provides MCP tools for interacting with Google Docs API and managing Google Docs via Drive.
"""
import pdb
import asyncio
import logging
import io
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from mcp import types
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# Auth & server utilities
from auth.service_decorator import require_google_service, require_multiple_services
from core.utils import extract_office_xml_text, handle_http_errors
from core.server import server
from core.comments import create_comment_tools

logger = logging.getLogger(__name__)

# Global cache for document content
# Structure: {document_id: {"content": processed_content, "timestamp": datetime, "tabs_data": dict}}
_document_cache: Dict[str, Dict[str, Any]] = {}
_cache_ttl_minutes = 30  # Time to live for cached documents


def _is_cache_valid(document_id: str) -> bool:
    """Check if cached document data is still valid."""
    if document_id not in _document_cache:
        return False
    
    cached_time = _document_cache[document_id].get("timestamp")
    if not cached_time:
        return False
    
    return datetime.now() - cached_time < timedelta(minutes=_cache_ttl_minutes)


def _get_cached_document(document_id: str) -> Optional[Dict[str, Any]]:
    """Get cached document data if valid."""
    if _is_cache_valid(document_id):
        return _document_cache[document_id]
    return None


def _cache_document(document_id: str, content: str, tabs_data: Dict[str, Any]) -> None:
    """Cache processed document content and tabs data."""
    _document_cache[document_id] = {
        "content": content,
        "tabs_data": tabs_data,
        "timestamp": datetime.now()
    }
    logger.info(f"Cached document {document_id}")


def _extract_document_content_with_tabs(docs_service, document_id: str) -> Dict[str, Any]:
    """
    Extract and process document content with tabs, including all metadata.
    
    Args:
        docs_service: Google Docs service instance
        document_id: ID of the document to process
        
    Returns:
        Dict containing processed content, tabs_data, and metadata
    """
    # Check cache first
    cached_data = _get_cached_document(document_id)
    if cached_data:
        logger.info(f"Using cached content for document {document_id}")
        return cached_data
    
    # Get document data from API
    doc_data = docs_service.documents().get(
        documentId=document_id,
        includeTabsContent=True
    ).execute()
    
    # Process all text formatting functions (moved from get_doc_content_with_tabs)
    def process_text_run(text_run):
        """Process a text run and extract content with formatting info."""
        content = text_run.get('content', '')
        text_style = text_run.get('textStyle', {})
        
        # Check for person properties (mentions, smart chips)
        if 'personProperties' in text_style:
            person_props = text_style['personProperties']
            email = person_props.get('email', '')
            name = person_props.get('name', content.strip())
            if email:
                return f"@{name} ({email})"
            else:
                return f"@{name}"
        
        # Check for rich link properties (smart chips, file links, etc.)
        if 'richLinkProperties' in text_style:
            rich_link = text_style['richLinkProperties']
            title = rich_link.get('title', content.strip())
            uri = rich_link.get('uri', '')
            mime_type = rich_link.get('mimeType', '')
            
            if uri:
                if mime_type:
                    return f"[{title}]({uri}) [{mime_type}]"
                else:
                    return f"[{title}]({uri})"
            else:
                return f"[RICH_LINK: {title}]"
        
        # Check for regular links
        if 'link' in text_style:
            link_url = text_style['link'].get('url', '')
            if link_url:
                return f"[{content.strip()}]({link_url})"
        
        # Check for formatting
        formatting = []
        if text_style.get('bold'):
            formatting.append('**')
        if text_style.get('italic'):
            formatting.append('*')
        if text_style.get('underline'):
            formatting.append('_')
        if text_style.get('strikethrough'):
            formatting.append('~~')
        
        # Check for color formatting
        if 'foregroundColor' in text_style:
            color = text_style['foregroundColor']
            if 'color' in color and 'rgbColor' in color['color']:
                rgb = color['color']['rgbColor']
                r = int(rgb.get('red', 0) * 255)
                g = int(rgb.get('green', 0) * 255)
                b = int(rgb.get('blue', 0) * 255)
                content = f"[COLOR(rgb({r},{g},{b})): {content}]"
        
        # Check for background color
        if 'backgroundColor' in text_style:
            bg_color = text_style['backgroundColor']
            if 'color' in bg_color and 'rgbColor' in bg_color['color']:
                rgb = bg_color['color']['rgbColor']
                r = int(rgb.get('red', 0) * 255)
                g = int(rgb.get('green', 0) * 255)
                b = int(rgb.get('blue', 0) * 255)
                content = f"[HIGHLIGHT(rgb({r},{g},{b})): {content}]"
        
        # Check for font properties
        if 'fontSize' in text_style:
            font_size = text_style['fontSize'].get('magnitude', 0)
            if font_size and font_size != 11:  # Only show if different from default
                content = f"[FONT_SIZE({font_size}pt): {content}]"
        
        if 'weightedFontFamily' in text_style:
            font_family = text_style['weightedFontFamily'].get('fontFamily', '')
            if font_family and font_family != 'Arial':  # Only show if different from default
                content = f"[FONT({font_family}): {content}]"
        
        if formatting:
            return f"{''.join(formatting)}{content}{''.join(reversed(formatting))}"
        
        return content
    
    def process_paragraph(paragraph):
        """Process a paragraph element and return formatted text."""
        para_elements = paragraph.get('elements', [])
        paragraph_text = ""
        
        for pe in para_elements:
            if 'textRun' in pe:
                paragraph_text += process_text_run(pe['textRun'])
            elif 'inlineObjectElement' in pe:
                # Handle images and other inline objects
                inline_obj = pe['inlineObjectElement']
                object_id = inline_obj.get('inlineObjectId', '')
                paragraph_text += f"[IMAGE: {object_id}]"
            elif 'pageBreak' in pe:
                paragraph_text += "[PAGE BREAK]"
            elif 'columnBreak' in pe:
                paragraph_text += "[COLUMN BREAK]"
            elif 'footnoteReference' in pe:
                footnote_ref = pe['footnoteReference']
                footnote_id = footnote_ref.get('footnoteId', '')
                footnote_number = footnote_ref.get('footnoteNumber', '')
                paragraph_text += f"[FOOTNOTE: {footnote_number}]"
            elif 'horizontalRule' in pe:
                paragraph_text += "\n---\n"
            elif 'equation' in pe:
                paragraph_text += "[EQUATION]"
            elif 'person' in pe:
                person = pe['person']
                person_id = person.get('personId', '')
                person_properties = person.get('personProperties', {})
                name = person_properties.get('name', 'Unknown Person')
                email = person_properties.get('email', '')
                if email:
                    paragraph_text += f"@{name} ({email})"
                else:
                    paragraph_text += f"@{name}"
        
        # Check for bullet points or numbering
        bullet = paragraph.get('bullet')
        if bullet:
            list_id = bullet.get('listId', '')
            nesting_level = bullet.get('nestingLevel', 0)
            indent = "  " * nesting_level
            
            # Check if it's numbered or bulleted
            if 'textStyle' in bullet:
                paragraph_text = f"{indent}• {paragraph_text}"
            else:
                paragraph_text = f"{indent}• {paragraph_text}"
        
        return paragraph_text.rstrip('\n')
    
    def process_table(table):
        """Process a table element and return formatted table."""
        table_content = []
        table_content.append("\n[TABLE]")
        
        rows = table.get('tableRows', [])
        for row_idx, row in enumerate(rows):
            row_content = []
            cells = row.get('tableCells', [])
            
            for cell in cells:
                cell_content = []
                cell_body = cell.get('content', [])
                
                for element in cell_body:
                    if 'paragraph' in element:
                        cell_text = process_paragraph(element['paragraph'])
                        if cell_text.strip():
                            cell_content.append(cell_text)
                
                row_content.append(' '.join(cell_content) if cell_content else '')
            
            table_content.append("| " + " | ".join(row_content) + " |")
            
            # Add separator after header row
            if row_idx == 0 and len(rows) > 1:
                table_content.append("| " + " | ".join(["-" * len(cell) for cell in row_content]) + " |")
        
        table_content.append("[/TABLE]\n")
        return '\n'.join(table_content)
    
    def process_content_elements(content_elements, indent=""):
        """Process a list of content elements (paragraphs, tables, etc.)."""
        processed = []
        
        for element in content_elements:
            if 'paragraph' in element:
                para_text = process_paragraph(element['paragraph'])
                if para_text.strip():
                    processed.append(f"{indent}{para_text}")
            
            elif 'table' in element:
                table_text = process_table(element['table'])
                processed.append(f"{indent}{table_text}")
            
            elif 'sectionBreak' in element:
                processed.append(f"{indent}[SECTION BREAK]")
            
            elif 'tableOfContents' in element:
                processed.append(f"{indent}[TABLE OF CONTENTS]")
        
        return processed
    
    def extract_document_metadata(doc_data):
        """Extract additional document metadata and properties."""
        metadata = []
        
        # Extract named ranges
        named_ranges = doc_data.get('namedRanges', {})
        if named_ranges:
            metadata.append("\n=== NAMED RANGES ===")
            for range_name, range_data in named_ranges.items():
                ranges = range_data.get('namedRanges', [])
                metadata.append(f"Range: {range_name}")
                for r in ranges:
                    start = r.get('range', {}).get('startIndex', 0)
                    end = r.get('range', {}).get('endIndex', 0)
                    metadata.append(f"  - Position: {start}-{end}")
        
        # Extract suggested changes
        suggested_changes = doc_data.get('suggestedChanges', {})
        if suggested_changes:
            metadata.append("\n=== SUGGESTED CHANGES ===")
            for change_id, change_data in suggested_changes.items():
                change_type = change_data.get('suggestionType', 'Unknown')
                metadata.append(f"Change ID: {change_id} - Type: {change_type}")
        
        # Extract footnotes
        footnotes = doc_data.get('footnotes', {})
        if footnotes:
            metadata.append("\n=== FOOTNOTES ===")
            for footnote_id, footnote_data in footnotes.items():
                content = footnote_data.get('content', [])
                footnote_text = []
                for element in content:
                    if 'paragraph' in element:
                        footnote_text.append(process_paragraph(element['paragraph']))
                metadata.append(f"Footnote {footnote_id}: {''.join(footnote_text)}")
        
        # Extract document style information
        doc_style = doc_data.get('documentStyle', {})
        if doc_style:
            metadata.append("\n=== DOCUMENT STYLE ===")
            
            # Page size
            page_size = doc_style.get('pageSize', {})
            if page_size:
                width = page_size.get('width', {}).get('magnitude', 0)
                height = page_size.get('height', {}).get('magnitude', 0)
                unit = page_size.get('width', {}).get('unit', 'PT')
                metadata.append(f"Page Size: {width} x {height} {unit}")
            
            # Margins
            margins = doc_style.get('marginTop', {})
            if margins:
                top = margins.get('magnitude', 0)
                unit = margins.get('unit', 'PT')
                metadata.append(f"Top Margin: {top} {unit}")
        
        # Extract lists information
        lists = doc_data.get('lists', {})
        if lists:
            metadata.append("\n=== LISTS ===")
            for list_id, list_data in lists.items():
                properties = list_data.get('listProperties', {})
                nesting_levels = properties.get('nestingLevels', [])
                metadata.append(f"List ID: {list_id} - Levels: {len(nesting_levels)}")
        
        return '\n'.join(metadata) if metadata else ""
    
    # Process document content
    processed_content = []
    processed_content.append('--- CONTENT ---')
    
    # Process main document body
    body = doc_data.get('body', {})
    if body:
        main_content = body.get('content', [])
        if main_content:
            processed_content.extend(process_content_elements(main_content))
    
    # Structure tabs data for easy access
    tabs_data = {}
    tabs = doc_data.get('tabs', [])
    pdb.set_trace()
    if tabs:
        processed_content.append("\n=== TABS CONTENT ===")
        for i, tab in enumerate(tabs):
            pdb.set_trace()
            tab_id = tab.get('tabId', f'tab_{i}')
            
            # Store tab data in structured format
            tab_info = {
                'tab_id': tab_id,
                'properties': tab.get('tabProperties', {}),
                'content': [],
                'child_tabs': {}
            }
            
            # Process tab properties
            tab_properties = tab.get('tabProperties', {})
            title = tab_properties.get('title', 'Untitled Tab')
            index = tab_properties.get('index', i)
            
            processed_content.append(f"\n--- TAB ID: {tab_id} ---")
            processed_content.append(f"Tab Title: {title}")
            processed_content.append(f"Tab Index: {index}")
            
            # Process tab content
            document_tab = tab.get('documentTab', {})
            if document_tab:
                body_content = document_tab.get('body', {}).get('content', [])
                if body_content:
                    processed_content.append("Tab Content:")
                    tab_processed = process_content_elements(body_content, "  ")
                    processed_content.extend(tab_processed)
                    tab_info['content'] = tab_processed
            
            # Process child tabs
            child_tabs = tab.get('childTabs', [])
            if child_tabs:
                processed_content.append(f"Child Tabs: {len(child_tabs)}")
                for j, child_tab in enumerate(child_tabs):
                    child_tab_id = child_tab.get('tabId', f'child_tab_{j}')
                    processed_content.append(f"  Child Tab ID: {child_tab_id}")
                    
                    child_doc_tab = child_tab.get('documentTab', {})
                    if child_doc_tab:
                        child_body = child_doc_tab.get('body', {}).get('content', [])
                        if child_body:
                            processed_content.append("  Child Tab Content:")
                            child_processed = process_content_elements(child_body, "    ")
                            processed_content.extend(child_processed)
                            
                            # Store child tab data
                            tab_info['child_tabs'][child_tab_id] = {
                                'tab_id': child_tab_id,
                                'properties': child_tab.get('tabProperties', {}),
                                'content': child_processed
                            }
            
            tabs_data[tab_id] = tab_info
    
    # Extract document metadata
    metadata = extract_document_metadata(doc_data)
    if metadata:
        processed_content.append("\n=== DOCUMENT METADATA ===")
        processed_content.append(metadata)
    
    # Prepare result
    result = {
        'content': '\n'.join(processed_content),
        'tabs_data': tabs_data,
        'doc_data': doc_data,
        'timestamp': datetime.now()
    }
    
    # Cache the result
    _cache_document(document_id, result['content'], tabs_data)
    
    return result


def _extract_tab_id_from_url(url_or_id: str) -> str:
    """
    Extract tab ID from Google Docs URL or return the ID as-is if it's already a tab ID.
    
    Args:
        url_or_id: Either a Google Docs URL with tab parameter or a direct tab ID
        
    Returns:
        str: Extracted or original tab ID
    """
    if url_or_id.startswith('http'):
        # Extract from URL: https://docs.google.com/document/d/.../edit?tab=t.xyz
        import urllib.parse
        parsed = urllib.parse.urlparse(url_or_id)
        query_params = urllib.parse.parse_qs(parsed.query)
        if 'tab' in query_params:
            return query_params['tab'][0]  # Return first tab parameter
    return url_or_id  # Return as-is if not a URL


@server.tool()
@require_multiple_services([
    {"service_type": "drive", "scopes": "drive_read", "param_name": "drive_service"},
    {"service_type": "docs", "scopes": "docs_read", "param_name": "docs_service"}
])
@handle_http_errors("get_tab_content")
async def get_tab_content(
    drive_service,
    docs_service,
    user_google_email: str,
    document_id: str,
    tab_identifier: str,
    parent_tab_id: Optional[str] = None,
    search_by_name: bool = False,
) -> str:
    """
    Unified function to retrieve content of tabs or subtabs from a Google Doc.
    Supports both direct IDs, Google Docs URLs with tab parameters, and searching by name.
    
    Args:
        user_google_email: The user's Google email address
        document_id: The ID of the Google Document
        tab_identifier: Tab ID, subtab ID, tab name, or Google Docs URL with tab parameter
        parent_tab_id: Optional parent tab ID (required for subtabs)
        search_by_name: If True, searches for tabs/subtabs by name instead of ID
    
    Returns:
        str: The content of the specified tab/subtab with metadata header.
    """
    # Extract tab ID from URL if needed
    tab_id = _extract_tab_id_from_url(tab_identifier)
    
    logger.info(f"[get_tab_content] Getting content for document {document_id}, tab: {tab_id}, parent: {parent_tab_id}, search_by_name: {search_by_name}")
    
    try:
        # Extract document content with tabs
        doc_result = await asyncio.to_thread(
            _extract_document_content_with_tabs,
            docs_service,
            document_id
        )
        
        tabs_data = doc_result.get('tabs_data', {})
        doc_title = doc_result.get('title', 'Unknown Document')
        doc_link = f"https://docs.google.com/document/d/{document_id}/edit?usp=drivesdk"
        
        response_parts = [
            f'File: "{doc_title}" (ID: {document_id}, Type: application/vnd.google-apps.document)',
            f'Link: {doc_link}',
            f'Requested Tab ID: {tab_id}',
            ''
        ]
        
        # If search_by_name is True, find tab/subtab by name instead of ID
        if search_by_name:
            search_lower = tab_id.lower()
            matches = []
            
            # Search through all tabs and subtabs by name
            for tab_id_key, tab_info in tabs_data.items():
                tab_properties = tab_info.get('properties', {})
                tab_title = tab_properties.get('title', 'Untitled Tab')
                
                # Check if main tab title matches
                if search_lower in tab_title.lower():
                    matches.append({
                        'type': 'tab',
                        'id': tab_id_key,
                        'title': tab_title,
                        'content': tab_info.get('content', []),
                        'parent_id': None,
                        'parent_title': None
                    })
                
                # Check subtabs
                child_tabs = tab_info.get('child_tabs', {})
                for subtab_id, subtab_info in child_tabs.items():
                    subtab_properties = subtab_info.get('properties', {})
                    subtab_title = subtab_properties.get('title', 'Untitled Subtab')
                    
                    if search_lower in subtab_title.lower():
                        matches.append({
                            'type': 'subtab',
                            'id': subtab_id,
                            'title': subtab_title,
                            'content': subtab_info.get('content', []),
                            'parent_id': tab_id_key,
                            'parent_title': tab_title
                        })
            
            if matches:
                response_parts.append(f'--- FOUND {len(matches)} MATCH(ES) BY NAME ---')
                response_parts.append('')
                
                for i, match in enumerate(matches, 1):
                    response_parts.append(f'Match {i} ({match["type"].upper()}):')
                    if match['type'] == 'subtab':
                        response_parts.extend([
                            f'Parent Tab: {match["parent_title"]} (ID: {match["parent_id"]})',
                            f'Subtab: {match["title"]} (ID: {match["id"]})',
                            '--- SUBTAB CONTENT ---'
                        ])
                    else:
                        response_parts.extend([
                            f'Tab: {match["title"]} (ID: {match["id"]})',
                            '--- TAB CONTENT ---'
                        ])
                    
                    # Add content
                    content = match['content']
                    if content:
                        response_parts.extend(content)
                    else:
                        response_parts.append('No content found.')
                    
                    response_parts.append('')  # Spacing between matches
            else:
                response_parts.extend([
                    f'--- NO MATCHES FOUND FOR NAME: "{tab_id}" ---',
                    '',
                    'Available tabs and subtabs in this document:'
                ])
                
                for tab_id_key, tab_info in tabs_data.items():
                    tab_properties = tab_info.get('properties', {})
                    tab_title = tab_properties.get('title', 'Untitled Tab')
                    response_parts.append(f'- Tab: "{tab_title}" (ID: {tab_id_key})')
                    
                    child_tabs = tab_info.get('child_tabs', {})
                    for subtab_id, subtab_info in child_tabs.items():
                        subtab_properties = subtab_info.get('properties', {})
                        subtab_title = subtab_properties.get('title', 'Untitled Subtab')
                        response_parts.append(f'  - Subtab: "{subtab_title}" (ID: {subtab_id})')
            
            return '\n'.join(response_parts)
        
        # If parent_tab_id is provided, look for subtab
        if parent_tab_id:
            if parent_tab_id in tabs_data:
                parent_tab = tabs_data[parent_tab_id]
                parent_properties = parent_tab.get('properties', {})
                parent_title = parent_properties.get('title', 'Untitled Tab')
                child_tabs = parent_tab.get('child_tabs', {})
                
                response_parts.append(f'Parent Tab ID: {parent_tab_id}')
                
                # Try to find subtab by exact ID match first
                target_subtab = None
                target_subtab_id = None
                
                for subtab_id, subtab_info in child_tabs.items():
                    if subtab_id == tab_id:
                        target_subtab = subtab_info
                        target_subtab_id = subtab_id
                        break
                
                # If not found by exact match, try partial match on web tab ID
                if not target_subtab:
                    for subtab_id, subtab_info in child_tabs.items():
                        subtab_properties = subtab_info.get('properties', {})
                        # Check if the web tab ID might correspond to this subtab
                        if tab_id.startswith('t.') and subtab_properties.get('index') is not None:
                            target_subtab = subtab_info
                            target_subtab_id = subtab_id
                            break
                
                if target_subtab:
                    subtab_properties = target_subtab.get('properties', {})
                    subtab_title = subtab_properties.get('title', 'Untitled Subtab')
                    subtab_index = subtab_properties.get('index', 0)
                    
                    response_parts.extend([
                        f'--- SUBTAB FOUND: {target_subtab_id} ---',
                        f'Parent Tab: {parent_title} (ID: {parent_tab_id})',
                        f'Subtab Title: {subtab_title}',
                        f'Subtab Index: {subtab_index}',
                        '',
                        '--- SUBTAB CONTENT ---'
                    ])
                    
                    # Extract content for this specific subtab
                    subtab_content = target_subtab.get('content', [])
                    if subtab_content:
                        response_parts.extend(subtab_content)
                    else:
                        response_parts.append('No content found in this subtab.')
                else:
                    response_parts.extend([
                        f'--- SUBTAB NOT FOUND: {tab_id} ---',
                        f'Parent Tab: {parent_title} (ID: {parent_tab_id})',
                        '',
                        'Available subtabs in this parent tab:'
                    ])
                    
                    for subtab_id, subtab_info in child_tabs.items():
                        subtab_properties = subtab_info.get('properties', {})
                        subtab_title = subtab_properties.get('title', 'Untitled Subtab')
                        response_parts.append(f'- Subtab ID: {subtab_id} | Title: "{subtab_title}"')
            else:
                response_parts.append(f'Parent tab {parent_tab_id} not found.')
        
        else:
            # Look for main tab or search through all tabs and subtabs
            found_content = False
            
            # Try exact match on main tabs first
            if tab_id in tabs_data:
                tab_info = tabs_data[tab_id]
                tab_properties = tab_info.get('properties', {})
                tab_title = tab_properties.get('title', 'Untitled Tab')
                tab_index = tab_properties.get('index', 0)
                
                response_parts.extend([
                    f'--- TAB FOUND: {tab_id} ---',
                    f'Tab Title: {tab_title}',
                    f'Tab Index: {tab_index}',
                    '',
                    '--- TAB CONTENT ---'
                ])
                
                # Extract content for this tab
                tab_content = tab_info.get('content', [])
                if tab_content:
                    response_parts.extend(tab_content)
                else:
                    response_parts.append('No content found in this tab.')
                
                # Show child tabs if any
                child_tabs = tab_info.get('child_tabs', {})
                if child_tabs:
                    response_parts.extend(['', '--- CHILD TABS ---'])
                    for child_id, child_info in child_tabs.items():
                        child_properties = child_info.get('properties', {})
                        child_title = child_properties.get('title', 'Untitled Child Tab')
                        response_parts.append(f'  - Child Tab ID: {child_id} | Title: "{child_title}"')
                
                found_content = True
            
            # If not found as main tab, search through all subtabs
            if not found_content:
                for parent_id, parent_tab in tabs_data.items():
                    child_tabs = parent_tab.get('child_tabs', {})
                    if tab_id in child_tabs:
                        parent_properties = parent_tab.get('properties', {})
                        parent_title = parent_properties.get('title', 'Untitled Tab')
                        
                        subtab_info = child_tabs[tab_id]
                        subtab_properties = subtab_info.get('properties', {})
                        subtab_title = subtab_properties.get('title', 'Untitled Subtab')
                        
                        response_parts.extend([
                            f'--- SUBTAB FOUND: {tab_id} ---',
                            f'Parent Tab: {parent_title} (ID: {parent_id})',
                            f'Subtab Title: {subtab_title}',
                            '',
                            '--- SUBTAB CONTENT ---'
                        ])
                        
                        subtab_content = subtab_info.get('content', [])
                        if subtab_content:
                            response_parts.extend(subtab_content)
                        else:
                            response_parts.append('No content found in this subtab.')
                        
                        found_content = True
                        break
            
            # If still not found, show available tabs
            if not found_content:
                response_parts.extend([
                    f'--- TAB NOT FOUND: {tab_id} ---',
                    '',
                    'Available tabs in this document:'
                ])
                
                for available_tab_id, tab_info in tabs_data.items():
                    tab_properties = tab_info.get('properties', {})
                    tab_title = tab_properties.get('title', 'Untitled Tab')
                    response_parts.append(f'- Tab ID: {available_tab_id} | Title: "{tab_title}" | Index: {tab_properties.get("index", 0)}')
                    
                    child_tabs = tab_info.get('child_tabs', {})
                    if child_tabs:
                        for child_id, child_info in child_tabs.items():
                            child_properties = child_info.get('properties', {})
                            child_title = child_properties.get('title', 'Untitled Child Tab')
                            response_parts.append(f'  - Child Tab ID: {child_id} | Title: "{child_title}"')
        
        return '\n'.join(response_parts)
        
    except Exception as e:
        return f"Error reading document tab: {str(e)}"


# Removed redundant search_subtabs function - functionality consolidated into get_tab_content


# Removed redundant get_specific_tab_content function - functionality consolidated into get_tab_content


@server.tool()
@require_multiple_services([
    {"service_type": "drive", "scopes": "drive_read", "param_name": "drive_service"},
    {"service_type": "docs", "scopes": "docs_read", "param_name": "docs_service"}
])
@handle_http_errors("list_docs_in_folder")
async def list_docs_in_folder(
    drive_service,
    docs_service,
    user_google_email: str,
    folder_id: str = 'root',
    page_size: int = 100
) -> str:
    """
    Lists Google Docs within a specific Drive folder.

    Returns:
        str: A formatted list of Google Docs in the specified folder.
    """
    logger.info(f"[list_docs_in_folder] Invoked. Email: '{user_google_email}', Folder ID: '{folder_id}'")

    rsp = await asyncio.to_thread(
        drive_service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false",
            pageSize=page_size,
            fields="files(id, name, modifiedTime, webViewLink)"
        ).execute
    )
    items = rsp.get('files', [])
    if not items:
        return f"No Google Docs found in folder '{folder_id}'."
    out = [f"Found {len(items)} Docs in folder '{folder_id}':"]
    for f in items:
        out.append(f"- {f['name']} (ID: {f['id']}) Modified: {f.get('modifiedTime')} Link: {f.get('webViewLink')}")
    return "\n".join(out)

@server.tool()
@require_google_service("drive", "drive_read")
@handle_http_errors("search_docs")
async def search_docs(
    service,
    user_google_email: str,
    query: str,
    page_size: int = 10,
) -> str:
    """
    Searches for Google Docs by name using Drive API (mimeType filter).

    Returns:
        str: A formatted list of Google Docs matching the search query.
    """
    logger.info(f"[search_docs] Email={user_google_email}, Query='{query}'")

    escaped_query = query.replace("'", "\\'")

    response = await asyncio.to_thread(
        service.files().list(
            q=f"name contains '{escaped_query}' and mimeType='application/vnd.google-apps.document' and trashed=false",
            pageSize=page_size,
            fields="files(id, name, createdTime, modifiedTime, webViewLink)"
        ).execute
    )
    files = response.get('files', [])
    if not files:
        return f"No Google Docs found matching '{query}'."

    output = [f"Found {len(files)} Google Docs matching '{query}':"]
    for f in files:
        output.append(
            f"- {f['name']} (ID: {f['id']}) Modified: {f.get('modifiedTime')} Link: {f.get('webViewLink')}"
        )
    return "\n".join(output)


@server.tool()
@require_multiple_services([
    {"service_type": "drive", "scopes": "drive_read", "param_name": "drive_service"},
    {"service_type": "docs", "scopes": "docs_read", "param_name": "docs_service"}
])
@handle_http_errors("get_doc_content")
async def get_doc_content(
    drive_service,
    docs_service,
    user_google_email: str,
    document_id: str,
) -> str:
    """
    Retrieves content of a Google Doc or a Drive file (like .docx) identified by document_id.
    - Native Google Docs: Fetches content via Docs API.
    - Office files (.docx, etc.) stored in Drive: Downloads via Drive API and extracts text.

    Returns:
        str: The document content with metadata header.
    """
    logger.info(f"[get_doc_content] Invoked. Document/File ID: '{document_id}' for user '{user_google_email}'")

    # Step 2: Get file metadata from Drive
    file_metadata = await asyncio.to_thread(
        drive_service.files().get(
            fileId=document_id, fields="id, name, mimeType, webViewLink"
        ).execute
    )
    mime_type = file_metadata.get("mimeType", "")
    file_name = file_metadata.get("name", "Unknown File")
    web_view_link = file_metadata.get("webViewLink", "#")

    logger.info(f"[get_doc_content] File '{file_name}' (ID: {document_id}) has mimeType: '{mime_type}'")

    body_text = "" # Initialize body_text

    # Step 3: Process based on mimeType
    if mime_type == "application/vnd.google-apps.document":
        logger.info(f"[get_doc_content] Processing as native Google Doc.")
        doc_data = await asyncio.to_thread(
            docs_service.documents().get(documentId=document_id).execute
        )
        body_elements = doc_data.get('body', {}).get('content', [])

        processed_text_lines: List[str] = []
        for element in body_elements:
            if 'paragraph' in element:
                paragraph = element.get('paragraph', {})
                para_elements = paragraph.get('elements', [])
                current_line_text = ""
                for pe in para_elements:
                    text_run = pe.get('textRun', {})
                    if text_run and 'content' in text_run:
                        current_line_text += text_run['content']
                if current_line_text.strip():
                        processed_text_lines.append(current_line_text)
        body_text = "".join(processed_text_lines)
    else:
        logger.info(f"[get_doc_content] Processing as Drive file (e.g., .docx, other). MimeType: {mime_type}")

        export_mime_type_map = {
                # Example: "application/vnd.google-apps.spreadsheet"z: "text/csv",
                # Native GSuite types that are not Docs would go here if this function
                # was intended to export them. For .docx, direct download is used.
        }
        effective_export_mime = export_mime_type_map.get(mime_type)

        request_obj = (
            drive_service.files().export_media(fileId=document_id, mimeType=effective_export_mime)
            if effective_export_mime
            else drive_service.files().get_media(fileId=document_id)
        )

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request_obj)
        loop = asyncio.get_event_loop()
        done = False
        while not done:
            status, done = await loop.run_in_executor(None, downloader.next_chunk)

        file_content_bytes = fh.getvalue()

        office_text = extract_office_xml_text(file_content_bytes, mime_type)
        if office_text:
            body_text = office_text
        else:
            try:
                body_text = file_content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                body_text = (
                    f"[Binary or unsupported text encoding for mimeType '{mime_type}' - "
                    f"{len(file_content_bytes)} bytes]"
                )

    header = (
        f'File: "{file_name}" (ID: {document_id}, Type: {mime_type})\n'
        f'Link: {web_view_link}\n\n--- CONTENT ---\n'
    )
    return header + body_text


@server.tool()
@require_google_service("docs", "docs_write")
@handle_http_errors("create_doc")
async def create_doc(
    service,
    user_google_email: str,
    title: str,
    content: str = '',
) -> str:
    """
    Creates a new Google Doc and optionally inserts initial content.

    Returns:
        str: Confirmation message with document ID and link.
    """
    logger.info(f"[create_doc] Invoked. Email: '{user_google_email}', Title='{title}'")

    doc = await asyncio.to_thread(service.documents().create(body={'title': title}).execute)
    doc_id = doc.get('documentId')
    if content:
        requests = [{'insertText': {'location': {'index': 1}, 'text': content}}]
        await asyncio.to_thread(service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute)
    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    msg = f"Created Google Doc '{title}' (ID: {doc_id}) for {user_google_email}. Link: {link}"
    logger.info(f"Successfully created Google Doc '{title}' (ID: {doc_id}) for {user_google_email}. Link: {link}")
    return msg


# Create comment management tools for documents
_comment_tools = create_comment_tools("document", "document_id")

# Extract and register the functions
read_doc_comments = _comment_tools['read_comments']
create_doc_comment = _comment_tools['create_comment']
reply_to_comment = _comment_tools['reply_to_comment']
resolve_comment = _comment_tools['resolve_comment']
