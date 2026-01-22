/**
 * Utility functions for the application
 */

// Anunciar mensajes a lectores de pantalla
export function announceCart(message) {
    const cartAnnouncements = document.getElementById('cart-announcements');
    if (!cartAnnouncements) return;
    // Limpiar y volver a establecer para forzar anuncio en lectores
    cartAnnouncements.textContent = '';
    setTimeout(() => {
        cartAnnouncements.textContent = message;
    }, 10);
}

// Escapar caracteres especiales en RegEx
export function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Resaltar términos de búsqueda (insensible a acentos)
export function highlightTerm(text, term) {
    if (!text || !term) return text || '';
    
    function buildAccentInsensitiveRegex(t) {
        const map = {
            'a': '[aáàäâ]','e': '[eéèëê]','i': '[iíìïî]','o': '[oóòöô]','u': '[uúùüû]',
            'n': '[nñ]','c': '[cç]'
        };
        let pattern = '';
        for (const ch of t) {
            const lower = ch.toLowerCase();
            if (map[lower]) {
                pattern += map[lower];
            } else {
                pattern += escapeRegExp(ch);
            }
        }
        return new RegExp('(' + pattern + ')', 'gi');
    }

    const regex = buildAccentInsensitiveRegex(term);
    return text.replace(regex, '<span class="highlight">$1</span>');
}

// Normalizar texto para búsqueda
export function normalizeForSearch(str) {
    return (str || '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '');
}

// Extraer fragmento de texto relevante
export function extractSnippet(text, term) {
    const termIndex = text.indexOf(term);
    const snippetStart = Math.max(0, termIndex - 50);
    const snippetEnd = Math.min(text.length, termIndex + term.length + 50);
    
    let snippet = text.substring(snippetStart, snippetEnd);
    if (snippetStart > 0) snippet = '...' + snippet;
    if (snippetEnd < text.length) snippet = snippet + '...';
    
    return snippet;
}

// Utilidad de accesibilidad: foco atrapado en diálogos
export function getFocusableElements(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll(
        'a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])'
    ));
}

let previouslyFocusedElement = null;

export function openDialog(dialog) {
    if (!dialog) return;
    previouslyFocusedElement = document.activeElement;
    dialog.setAttribute('aria-hidden', 'false');
    if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
    
    const focusables = getFocusableElements(dialog);
    const first = focusables[0] || dialog;
    const last = focusables[focusables.length - 1] || dialog;
    
    function trap(e) {
        if (e.key === 'Tab') {
            if (focusables.length === 0) { e.preventDefault(); return; }
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }
    
    dialog.addEventListener('keydown', trap);
    dialog._trapHandler = trap;
    first.focus();
}

export function closeDialog(dialog) {
    if (!dialog) return;
    dialog.setAttribute('aria-hidden', 'true');
    dialog.removeAttribute('tabindex');
    if (dialog._trapHandler) {
        dialog.removeEventListener('keydown', dialog._trapHandler);
        delete dialog._trapHandler;
    }
    if (previouslyFocusedElement) {
        previouslyFocusedElement.focus();
        previouslyFocusedElement = null;
    }
}

// Resaltar elemento en la UI (scroll + animación)
export function highlightElement(element) {
    if (!element) return;
    
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    // Añadir clase para animación visual si existe CSS, o borde temporal
    element.classList.add('highlight-pulse');
    
    // Fallback visual inline si no hay CSS
    const originalTransition = element.style.transition;
    const originalBoxShadow = element.style.boxShadow;
    
    element.style.transition = 'box-shadow 0.5s ease';
    element.style.boxShadow = '0 0 0 4px rgba(255, 106, 0, 0.5)';
    
    setTimeout(() => {
        element.classList.remove('highlight-pulse');
        element.style.boxShadow = originalBoxShadow;
        setTimeout(() => {
            element.style.transition = originalTransition;
        }, 500);
    }, 2000);
}
