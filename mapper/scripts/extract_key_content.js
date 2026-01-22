/**
 * Extract key paragraphs from main content (excluding nav/footer/sidebar and cookie/privacy consent dialogs).
 * Returns joined string of paragraph previews.
 */
(() => {
    const paragraphs = [];
    const pTags = document.querySelectorAll('p, .content p, main p, article p, [role="main"] p');
    
    for (const p of pTags) {
        // Skip paragraphs in nav/footer/sidebar
        const parent = p.closest('nav, footer, header, aside, .nav, .footer, .sidebar');
        if (parent) continue;
        
        // Skip paragraphs in cookie/privacy consent dialogs
        const consentParent = p.closest(
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
        
        const text = p.innerText.trim();
        
        // Skip paragraphs with cookie/consent/privacy-related content
        const textLower = text.toLowerCase();
        if (textLower.includes('cookie') || 
            textLower.includes('consent') || 
            textLower.includes('privacy policy') ||
            textLower.includes('accept cookies') ||
            textLower.includes('cookie settings') ||
            textLower.includes('we use cookies') ||
            textLower.includes('this website uses cookies')) {
            continue;
        }
        
        // Only include meaningful paragraphs (not empty, not just numbers)
        if (text && text.length > 20 && !text.match(/^[\d\s\$.,%()-]+$/)) {
            // Take first 1-2 sentences (up to 200 chars)
            const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
            const preview = sentences.slice(0, 2).join(' ').substring(0, 200);
            paragraphs.push(preview);
            if (paragraphs.length >= 3) break; // Limit to 3 paragraphs
        }
    }
    return paragraphs.join(' | ');
})();
