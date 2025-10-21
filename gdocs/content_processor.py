"""
Document content processing module for Google Docs.

Handles parsing, formatting, and extraction of document content including:
- Text runs with formatting (bold, italic, colors, fonts)
- Paragraphs with bullets and numbering
- Tables
- Images and inline objects
- Metadata (named ranges, footnotes, document styles)
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

from gdocs.cache import get_cached_document, cache_document

logger = logging.getLogger(__name__)


def extract_document_content_with_tabs(docs_service, document_id: str) -> Dict[str, Any]:
    """
    Extract and process document content with tabs, including all metadata.
    
    Args:
        docs_service: Google Docs service instance
        document_id: ID of the document to process
        
    Returns:
        Dict containing processed content, tabs_data, and metadata
    """
    # Check cache first
    cached_data = get_cached_document(document_id)
    if cached_data:
        logger.info(f"Using cached content for document {document_id}")
        return cached_data
    
    # Get document data from API
    doc_data = docs_service.documents().get(
        documentId=document_id,
        includeTabsContent=True
    ).execute()
    
    # Process all text formatting functions
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
                # Case 1: Direct URL as content
                if content.strip() == link_url:
                    return f"[LINK: {link_url}]"
                # Case 2: Custom text with URL
                else:
                    return f"[LINK: {content.strip()} -> {link_url}]"
        
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
    
    def process_paragraph(paragraph, inline_objects=None):
        """Process a paragraph element and return formatted text."""
        para_elements = paragraph.get('elements', [])
        paragraph_text = ""
        
        for pe in para_elements:
            if 'textRun' in pe:
                paragraph_text += process_text_run(pe['textRun'])
            elif 'inlineObjectElement' in pe:
                # Handle images and other inline objects with rich information
                inline_obj = pe['inlineObjectElement']
                object_id = inline_obj.get('inlineObjectId', '')
                
                # Try to get image URI from inline_objects
                if inline_objects and object_id in inline_objects:
                    inline_data = inline_objects[object_id]
                    embedded_obj = inline_data.get('inlineObjectProperties', {}).get('embeddedObject', {})
                    image_props = embedded_obj.get('imageProperties', {})
                    content_uri = image_props.get('contentUri', '')
                    
                    # Get additional image properties for better display
                    title = embedded_obj.get('title', '')
                    description = embedded_obj.get('description', '')
                    
                    if content_uri:
                        # Display the image inline using markdown syntax
                        alt_text = title or description or f"Image {object_id}"
                        paragraph_text += f"![{alt_text}]({content_uri})"
                    else:
                        # Fallback if no URI available
                        paragraph_text += f"[IMAGE: {object_id}]"
                else:
                    # Fallback to basic format if no inline_objects data available
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
    
    def process_table(table, inline_objects=None):
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
                        cell_text = process_paragraph(element['paragraph'], inline_objects)
                        if cell_text.strip():
                            cell_content.append(cell_text)
                
                row_content.append(' '.join(cell_content) if cell_content else '')
            
            table_content.append("| " + " | ".join(row_content) + " |")
            
            # Add separator after header row
            if row_idx == 0 and len(rows) > 1:
                table_content.append("| " + " | ".join(["-" * len(cell) for cell in row_content]) + " |")
        
        table_content.append("[/TABLE]\n")
        return '\n'.join(table_content)
    
    def process_content_elements(content_elements, indent="", inline_objects=None):
        """Process a list of content elements (paragraphs, tables, etc.)."""
        processed = []
        
        for element in content_elements:
            if 'paragraph' in element:
                para_text = process_paragraph(element['paragraph'], inline_objects)
                if para_text.strip():
                    processed.append(f"{indent}{para_text}")
            
            elif 'table' in element:
                table_text = process_table(element['table'], inline_objects)
                processed.append(f"{indent}{table_text}")
            
            elif 'sectionBreak' in element:
                processed.append(f"{indent}[SECTION BREAK]")
            
            elif 'tableOfContents' in element:
                processed.append(f"{indent}[TABLE OF CONTENTS]")
        
        return processed
    
    def extract_document_metadata(doc_data, inline_objects=None):
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
                        footnote_text.append(process_paragraph(element['paragraph'], inline_objects))
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
    
    # Extract inline objects for rich image processing
    inline_objects = doc_data.get('inlineObjects', {})
    
    # Process document content
    processed_content = []
    processed_content.append('--- CONTENIDO ---')
    
    # Process main document body
    body = doc_data.get('body', {})
    if body:
        main_content = body.get('content', [])
        if main_content:
            processed_content.extend(process_content_elements(main_content, inline_objects=inline_objects))
    
    # Structure tabs data for easy access
    tabs_data = {}
    tabs = doc_data.get('tabs', [])
    if tabs:
        processed_content.append("\n=== CONTENIDO DE PESTAÑAS ===")
        for i, tab in enumerate(tabs):
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
            
            processed_content.append(f"\n--- ID DE PESTAÑA: {tab_id} ---")
            processed_content.append(f"Título de Pestaña: {title}")
            processed_content.append(f"Índice de Pestaña: {index}")
            
            # Process tab content
            document_tab = tab.get('documentTab', {})
            if document_tab:
                # Get tab-specific inline objects if available, otherwise use document-level ones
                tab_inline_objects = document_tab.get('inlineObjects', inline_objects)
                body_content = document_tab.get('body', {}).get('content', [])
                if body_content:
                    processed_content.append("Contenido de Pestaña:")
                    tab_processed = process_content_elements(body_content, "  ", tab_inline_objects)
                    processed_content.extend(tab_processed)
                    tab_info['content'] = tab_processed
            
            # Process child tabs
            child_tabs = tab.get('childTabs', [])
            if child_tabs:
                processed_content.append(f"Pestañas secundarias: {len(child_tabs)}")
                for j, child_tab in enumerate(child_tabs):
                    child_tab_id = child_tab.get('tabId', f'child_tab_{j}')
                    processed_content.append(f"  ID de Pestaña Secundaria: {child_tab_id}")
                    
                    child_doc_tab = child_tab.get('documentTab', {})
                    if child_doc_tab:
                        # Get child tab-specific inline objects if available, otherwise use document-level ones
                        child_inline_objects = child_doc_tab.get('inlineObjects', inline_objects)
                        child_body = child_doc_tab.get('body', {}).get('content', [])
                        if child_body:
                            processed_content.append("  Contenido de Pestaña Secundaria:")
                            child_processed = process_content_elements(child_body, "    ", child_inline_objects)
                            processed_content.extend(child_processed)
                            
                            # Store child tab data
                            tab_info['child_tabs'][child_tab_id] = {
                                'tab_id': child_tab_id,
                                'properties': child_tab.get('tabProperties', {}),
                                'content': child_processed
                            }
            
            tabs_data[tab_id] = tab_info
    
    # Extract document metadata
    metadata = extract_document_metadata(doc_data, inline_objects)
    if metadata:
        processed_content.append("\n=== METADATOS DEL DOCUMENTO ===")
        processed_content.append(metadata)
    
    # Prepare result
    result = {
        'content': '\n'.join(processed_content),
        'tabs_data': tabs_data,
        'doc_data': doc_data,
        'timestamp': datetime.now()
    }
    
    # Cache the result
    cache_document(document_id, result['content'], tabs_data)
    
    return result
