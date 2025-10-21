# Google Docs Module - Refactored Structure

## Overview

This module has been refactored from a single 1,302-line file into focused, responsibility-based modules for better AI context delivery and maintainability.

## Module Structure

```
gdocs/
├── __init__.py              # Module initialization, imports tools
├── cache.py                 # Document caching logic (~50 lines)
├── utils.py                 # Helper utilities (~100 lines)
├── content_processor.py     # Document parsing & formatting (~450 lines)
├── tools.py                 # MCP tool definitions (~750 lines)
└── docs_tools.py.backup     # Original monolithic file (backup)
```

## Module Responsibilities

### `cache.py`
**Purpose**: Document caching to reduce API calls

**Functions**:
- `is_cache_valid(document_id)` - Check if cached data is still valid
- `get_cached_document(document_id)` - Retrieve cached document
- `cache_document(document_id, content, tabs_data)` - Store document in cache
- `clear_cache(document_id)` - Invalidate cache for a document

**Cache TTL**: 30 minutes

---

### `utils.py`
**Purpose**: Helper utilities for URL parsing and lightweight operations

**Functions**:
- `extract_tab_id_from_url(url_or_id)` - Extract tab ID from Google Docs URL
- `get_tab_content_lightweight(docs_service, document_id, tab_id)` - Fast tab loading without full document processing
- `format_tab_selection_prompt(doc_title, tabs_count)` - Generate user-friendly prompts

---

### `content_processor.py`
**Purpose**: Document content parsing and formatting

**Main Function**:
- `extract_document_content_with_tabs(docs_service, document_id)` - Complete document processing

**Features**:
- Text formatting (bold, italic, colors, fonts)
- Links and rich links (smart chips)
- Images and inline objects
- Tables with markdown formatting
- Paragraphs with bullets and numbering
- Document metadata (named ranges, footnotes, styles)
- Tab and subtab processing

**Internal Functions** (nested):
- `process_text_run()` - Handle text formatting
- `process_paragraph()` - Process paragraph elements
- `process_table()` - Format tables
- `process_content_elements()` - Process mixed content
- `extract_document_metadata()` - Extract document properties

---

### `tools.py`
**Purpose**: MCP tool definitions for Google Docs operations

**Tools** (5 total):

1. **`get_tab_content`**
   - Retrieve content from specific tabs/subtabs
   - Supports search by name or ID
   - Optimized with lightweight loading
   - Parameters: `document_id`, `tab_identifier`, `parent_tab_id`, `search_by_name`

2. **`read_doc_comments`**
   - Read all comments and replies from a document
   - Parameters: `document_id`

3. **`reply_to_comment`**
   - Reply to a specific comment
   - Parameters: `document_id`, `comment_id`, `reply_content`

4. **`edit_tab_content`**
   - Add content to a specific tab
   - Supports position control (beginning/end)
   - Parameters: `document_id`, `tab_identifier`, `content_to_add`, `position`

5. **`create_doc_comment`**
   - Create a new comment on a document
   - Parameters: `document_id`, `comment_content`

---

## Benefits of This Structure

### For AI Models:
✅ **Focused Context**: Each file has a single, clear purpose  
✅ **Reduced Token Usage**: Load only relevant modules (~200-450 lines vs 1,302)  
✅ **Clear Dependencies**: Import statements document relationships  
✅ **Easier Navigation**: Grep/search finds specific logic faster  

### For Developers:
✅ **Maintainability**: Changes are isolated to specific concerns  
✅ **Testability**: Each module can be tested independently  
✅ **Readability**: Smaller files are easier to understand  
✅ **Reusability**: Modules can be imported independently  

## Migration Notes

- **Original file**: Backed up as `docs_tools.py.backup`
- **No functionality changes**: All tools work identically
- **Import changes**: Internal functions now imported from specialized modules
- **Cache management**: Now centralized in `cache.py`

## Usage Example

```python
# Import specific modules as needed
from gdocs.cache import get_cached_document, cache_document
from gdocs.utils import extract_tab_id_from_url
from gdocs.content_processor import extract_document_content_with_tabs

# Tools are automatically registered via __init__.py
from gdocs import tools  # Registers all 5 MCP tools
```

## File Size Comparison

| File | Lines | Purpose |
|------|-------|---------|
| **Original** | 1,302 | Everything |
| `cache.py` | ~50 | Caching |
| `utils.py` | ~100 | Utilities |
| `content_processor.py` | ~450 | Parsing |
| `tools.py` | ~750 | MCP Tools |
| **Total New** | ~1,350 | Organized by responsibility |

## Testing

To verify the refactoring:

```bash
# Check imports (requires dependencies)
python3 -c "from gdocs import cache, utils, content_processor, tools"

# Run the MCP server
python3 main.py --tools docs
```

All functionality remains identical to the original implementation.
