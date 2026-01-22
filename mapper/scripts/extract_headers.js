/**
 * Extract page headers (h1-h4 prioritized, then h5-h6) excluding navigation/footer headers and cookie/privacy consent dialogs.
 * Returns array of header objects with level and text, prioritized by h1-h4.
 */
(() => {
    const headers = [];
    
    // First, collect h1-h4 (prioritized)
    const priorityTags = ['h1', 'h2', 'h3', 'h4'];
    for (const tag of priorityTags) {
        const hTags = document.querySelectorAll(tag);
        for (const h of hTags) {
            const text = h.innerText.trim();
            
            // Skip headers in nav/footer (common patterns)
            const parent = h.closest('nav, footer, header, .nav, .footer, .header');
            if (parent) continue;
            
            // Skip headers in cookie/privacy consent dialogs
            const consentParent = h.closest(
                '.cookie-consent, .cookie-banner, .cookie-notice, ' +
                '.privacy-consent, .privacy-banner, .privacy-notice, ' +
                '[id*="cookie" i], [class*="cookie" i], ' +
                '[id*="consent" i], [class*="consent" i], ' +
                '[id*="privacy" i], [class*="privacy" i], ' +
                '[role="dialog"][aria-label*="cookie" i], ' +
                '[role="dialog"][aria-label*="consent" i], ' +
                '[role="dialog"][aria-label*="privacy" i]'
            );
            if (consentParent) continue;
            
            // Skip headers with cookie/consent/privacy-related text
            const textLower = text.toLowerCase();
            if (textLower.includes('cookie') || 
                textLower.includes('consent') || 
                textLower.includes('privacy policy') ||
                textLower.includes('accept cookies') ||
                textLower.includes('cookie settings')) {
                continue;
            }
            
            if (text && text.length > 0) {
                headers.push({
                    level: tag,
                    text: text
                });
            }
        }
    }
    
    // Then, collect h5-h6 (if we haven't hit the limit)
    const secondaryTags = ['h5', 'h6'];
    for (const tag of secondaryTags) {
        if (headers.length >= 20) break; // Limit total headers to 20
        
        const hTags = document.querySelectorAll(tag);
        for (const h of hTags) {
            if (headers.length >= 20) break;
            
            const text = h.innerText.trim();
            
            // Skip headers in nav/footer (common patterns)
            const parent = h.closest('nav, footer, header, .nav, .footer, .header');
            if (parent) continue;
            
            // Skip headers in cookie/privacy consent dialogs
            const consentParent = h.closest(
                '.cookie-consent, .cookie-banner, .cookie-notice, ' +
                '.privacy-consent, .privacy-banner, .privacy-notice, ' +
                '[id*="cookie" i], [class*="cookie" i], ' +
                '[id*="consent" i], [class*="consent" i], ' +
                '[id*="privacy" i], [class*="privacy" i], ' +
                '[role="dialog"][aria-label*="cookie" i], ' +
                '[role="dialog"][aria-label*="consent" i], ' +
                '[role="dialog"][aria-label*="privacy" i]'
            );
            if (consentParent) continue;
            
            // Skip headers with cookie/consent/privacy-related text
            const textLower = text.toLowerCase();
            if (textLower.includes('cookie') || 
                textLower.includes('consent') || 
                textLower.includes('privacy policy') ||
                textLower.includes('accept cookies') ||
                textLower.includes('cookie settings')) {
                continue;
            }
            
            if (text && text.length > 0) {
                headers.push({
                    level: tag,
                    text: text
                });
            }
        }
    }
    
    // Return as array of text strings (for backward compatibility) but prioritize h1-h4
    // All h1-h4 headers are included, then h5-h6 up to limit of 20
    return headers.map(h => h.text);
})();
