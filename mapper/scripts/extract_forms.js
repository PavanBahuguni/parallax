/**
 * Extract form field information, excluding cookie/privacy consent forms.
 * Returns array of strings describing forms and their fields.
 */
(() => {
    const formInfo = [];
    const forms = document.querySelectorAll('form');
    for (const form of forms) {
        // Skip cookie/privacy consent forms
        const formId = (form.getAttribute('id') || '').toLowerCase();
        const formClass = (form.getAttribute('class') || '').toLowerCase();
        const formAriaLabel = (form.getAttribute('aria-label') || '').toLowerCase();
        
        if (formId.includes('cookie') || formId.includes('consent') || formId.includes('privacy') ||
            formClass.includes('cookie') || formClass.includes('consent') || formClass.includes('privacy') ||
            formAriaLabel.includes('cookie') || formAriaLabel.includes('consent') || formAriaLabel.includes('privacy')) {
            continue;
        }
        
        // Check if form is inside a cookie/privacy consent dialog
        const consentParent = form.closest(
            '.cookie-consent, .cookie-banner, .cookie-notice, ' +
            '.privacy-consent, .privacy-banner, .privacy-notice, ' +
            '[id*="cookie" i], [class*="cookie" i], ' +
            '[id*="consent" i], [class*="consent" i], ' +
            '[id*="privacy" i], [class*="privacy" i]'
        );
        if (consentParent) continue;
        
        // Get field names/labels
        const fields = [];
        const inputs = form.querySelectorAll('input, textarea, select');
        for (const inp of inputs) {
            const name = inp.getAttribute('name') || inp.getAttribute('placeholder') || inp.getAttribute('id') || '';
            if (name && name.length > 0) {
                // Skip cookie/consent-related field names
                const nameLower = name.toLowerCase();
                if (nameLower.includes('cookie') || nameLower.includes('consent') || nameLower.includes('privacy')) {
                    continue;
                }
                fields.push(name);
            }
        }
        if (fields.length > 0) {
            formInfo.push(`Form with fields: ${fields.slice(0, 8).join(', ')}${fields.length > 8 ? '...' : ''}`);
        }
    }
    return formInfo.slice(0, 3); // Limit to 3 forms
})();
