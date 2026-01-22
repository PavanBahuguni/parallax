# Playwright Scripts

This directory contains JavaScript scripts used by the semantic mapper for extracting structured information from web pages.

## Scripts

- **`extract_headers.js`** - Extracts page headers (h1-h6) excluding navigation/footer headers
- **`extract_tables.js`** - Extracts table column information
- **`extract_forms.js`** - Extracts form field information
- **`extract_key_content.js`** - Extracts key paragraphs from main content

## Usage

These scripts are automatically loaded by `semantic_mapper_with_gateway.py` using the `_load_playwright_script()` helper function. They are executed in the browser context via `page.evaluate()`.

## Benefits

- **Better syntax highlighting** - JavaScript files get proper IDE support
- **Easier to maintain** - Scripts can be edited independently
- **Testable** - Scripts can be tested separately if needed
- **Cleaner Python code** - Reduces inline JavaScript clutter
