/**
 * Extract table column information.
 * Returns array of strings describing tables and their columns.
 */
(() => {
    const tableInfo = [];
    const tables = document.querySelectorAll('table');
    for (const table of tables) {
        // Get column headers (th elements)
        const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th, tr:first-child td'))
            .map(th => th.innerText.trim())
            .filter(text => text && text.length > 0 && !text.match(/^\$?[\d.,]+[KM]?$/)) // Skip numeric headers
            .slice(0, 10); // Limit columns
        
        if (headers.length > 0) {
            tableInfo.push(`Table with columns: ${headers.join(', ')}`);
        }
    }
    return tableInfo.slice(0, 3); // Limit to 3 tables
})();
