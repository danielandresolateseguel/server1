/**
 * Search Logic
 */
import { normalizeForSearch, extractSnippet, highlightTerm, highlightElement } from './utils.js';
import { addToCart } from './cart.js';
import { showAddToCartAnimation, showAddedToCartIndicator } from './ui.js';

export let searchableItems = [];

const SEARCH_HISTORY_KEY = 'search_history';

// Datos de sugerencias
const searchSuggestions = [
    { text: 'laptop', type: 'producto', icon: 'fas fa-laptop' },
    { text: 'notebook', type: 'producto', icon: 'fas fa-laptop' },
    { text: 'computadora', type: 'producto', icon: 'fas fa-desktop' },
    { text: 'gaming', type: 'categoría', icon: 'fas fa-gamepad' },
    { text: 'asus', type: 'marca', icon: 'fas fa-tag' },
    { text: 'xbox', type: 'producto', icon: 'fab fa-xbox' },
    { text: 'consola', type: 'producto', icon: 'fas fa-gamepad' },
    { text: 'procesador', type: 'componente', icon: 'fas fa-microchip' },
    { text: 'memoria', type: 'componente', icon: 'fas fa-memory' },
    { text: 'ram', type: 'componente', icon: 'fas fa-memory' },
    { text: 'ssd', type: 'componente', icon: 'fas fa-hdd' },
    { text: 'disco', type: 'componente', icon: 'fas fa-hdd' },
    { text: 'gráfica', type: 'componente', icon: 'fas fa-tv' },
    { text: 'monitor', type: 'producto', icon: 'fas fa-desktop' },
    { text: 'teclado', type: 'accesorio', icon: 'fas fa-keyboard' },
    { text: 'mouse', type: 'accesorio', icon: 'fas fa-mouse' },
    { text: 'auriculares', type: 'accesorio', icon: 'fas fa-headphones' }
];

let searchHistory = JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY)) || [];
let currentSuggestionIndex = -1;
let filteredSuggestions = [];
let searchTimeout;

export function refreshSearchableItems() {
    searchableItems = document.querySelectorAll('.searchable-item');
}

const SYNONYMS_GROUPS = [
    ['smartphone','celu','celular','telefono','movil','móvil','phone'],
    ['laptop','notebook','portatil','portátil','compu','computadora','pc'],
    ['auriculares','headphones','cascos'],
    ['altavoz','parlante','speaker'],
    ['camara','cámara','dslr'],
    ['monitor','pantalla'],
    ['teclado','keyboard'],
    ['mouse','raton','ratón'],
    ['promo','promocion','oferta','liquidacion'],
    ['xbox','consola'],
    ['playstation','ps4','ps5'],
    ['nintendo','switch'],
    ['tv','televisor','tele','smart tv'],
    ['smartwatch','reloj inteligente','watch'],
    ['tablet','tableta','ipad'],
    ['impresora','printer'],
    ['memoria','ram'],
    ['disco','ssd','solid state'],
    ['router','modem','ruteador'],
    ['heladera','refrigerador','nevera'],
    ['lavarropas','lavadora'],
    ['microondas','micro'],
    ['hamburguesa','hamb'],
    ['pizza','pizzas'],
    ['empanada','empanadas'],
    ['coctel','cóctel','bebida','trago','drink'],
    ['cafe','café','cafetera','espresso'],
    ['cerveza','birra'],
    ['vino','tinto','blanco'],
    ['postre','dulce','dessert'],
    ['ensalada','salad'],
    ['sandwich','sándwich','tostado'],
    ['gaseosa','refresco','soda'],
    ['helado','ice cream'],
    ['combo','pack']
].map(group => group.map(normalizeForSearch));

function expandSynonyms(term) {
    const t = normalizeForSearch(term);
    const variants = new Set([t]);
    SYNONYMS_GROUPS.forEach(group => {
        if (group.some(word => t.includes(word))) {
            group.forEach(word => variants.add(word));
        }
    });
    return Array.from(variants);
}

function buildSearchText(item) {
    const texts = [
        item.textContent,
        item.getAttribute('data-food-category'),
        item.getAttribute('data-product-category'),
        item.getAttribute('data-tags')
    ];
    const img = item.querySelector('.product-image img');
    if (img) texts.push(img.alt);
    const btn = item.querySelector('.add-to-cart-btn');
    if (btn) {
        texts.push(btn.getAttribute('data-name'));
        texts.push(btn.getAttribute('data-id'));
    }
    return normalizeForSearch(texts.filter(Boolean).join(' '));
}

export function performSearch(term, items) {
    const results = [];
    items.forEach(item => {
        if (matchesSearch(term, item)) {
            const addToCartBtn = item.querySelector('.add-to-cart-btn');
            const productImage = item.querySelector('.product-image img');
            const productDescription = item.querySelector('.product-description');
            const productPrice = item.querySelector('.product-price');
            const titleEl = item.querySelector('h3');
            
            const matchedVariant = findMatchedVariant(term, item);
            
            results.push({
                id: item.id,
                title: titleEl ? titleEl.textContent : (addToCartBtn ? addToCartBtn.getAttribute('data-name') : ''),
                snippet: extractSnippet((item.textContent || '').toLowerCase(), (matchedVariant || term)),
                image: productImage ? productImage.src : '',
                imageAlt: productImage ? productImage.alt : '',
                description: productDescription ? productDescription.textContent : '',
                price: productPrice ? productPrice.textContent : '',
                productId: addToCartBtn ? addToCartBtn.getAttribute('data-id') : '',
                productName: addToCartBtn ? addToCartBtn.getAttribute('data-name') : '',
                productPrice: addToCartBtn ? addToCartBtn.getAttribute('data-price') : '',
                matchedVariant: matchedVariant
            });
        }
    });
    return results;
}

function matchesSearch(term, item) {
    const variants = expandSynonyms(term);
    const text = buildSearchText(item);
    return variants.some(v => text.includes(v));
}

function findMatchedVariant(term, item) {
    const variants = expandSynonyms(term);
    const text = buildSearchText(item);
    return variants.find(v => text.includes(v)) || null;
}

export function displayResults(results, term, container) {
    container.innerHTML = '';
    
    if (results.length === 0) {
        container.innerHTML = '<p class="no-results">No se encontraron resultados para "' + term + '".</p>';
        return;
    }
    
    results.forEach(result => {
        const resultItem = document.createElement('div');
        resultItem.className = 'search-result-item';
        
        const resultImageContainer = document.createElement('div');
        resultImageContainer.className = 'search-result-image';
        if (result.image) {
            const resultImage = document.createElement('img');
            resultImage.src = result.image;
            resultImage.alt = result.imageAlt;
            resultImage.loading = 'lazy';
            resultImageContainer.appendChild(resultImage);
        } else {
            resultImageContainer.innerHTML = '<div class="image-placeholder"><i class="fas fa-image"></i></div>';
        }
        
        const resultInfo = document.createElement('div');
        resultInfo.className = 'search-result-info';
        
        const resultTitle = document.createElement('h3');
        resultTitle.className = 'search-result-title';
        resultTitle.innerHTML = highlightTerm(result.title, result.matchedVariant || term);
        
        const resultDescription = document.createElement('p');
        resultDescription.className = 'search-result-description';
        resultDescription.innerHTML = highlightTerm(result.description, result.matchedVariant || term);
        
        const resultPrice = document.createElement('p');
        resultPrice.className = 'search-result-price';
        resultPrice.innerHTML = highlightTerm(result.price, result.matchedVariant || term);
        
        resultInfo.append(resultTitle, resultDescription, resultPrice);
        
        const resultActions = document.createElement('div');
        resultActions.className = 'search-result-actions';
        
        if (result.productId) {
            const addToCartBtn = document.createElement('button');
            addToCartBtn.className = 'search-add-to-cart-btn';
            addToCartBtn.innerHTML = '<i class="fas fa-cart-plus"></i> Agregar';
            addToCartBtn.setAttribute('data-id', result.productId);
            addToCartBtn.setAttribute('data-name', result.productName);
            addToCartBtn.setAttribute('data-price', result.productPrice);
            
            addToCartBtn.addEventListener('click', function(e) {
                e.preventDefault();
                const price = parseInt(this.getAttribute('data-price'));
                addToCart(result.productId, result.productName, price, result.image, e, (evt) => {
                    showAddToCartAnimation(evt);
                });
                
                this.innerHTML = '<i class="fas fa-check"></i> Agregado';
                this.style.backgroundColor = '#28a745';
                setTimeout(() => {
                    this.innerHTML = '<i class="fas fa-cart-plus"></i> Agregar';
                    this.style.backgroundColor = '';
                }, 2000);
            });
            resultActions.appendChild(addToCartBtn);
        }
        
        const resultLink = document.createElement('button');
        resultLink.className = 'search-view-more-btn';
        resultLink.innerHTML = '<i class="fas fa-eye"></i> Ver más';
        resultLink.addEventListener('click', function(e) {
            e.preventDefault();
            const searchResultsSection = document.querySelector('.search-results');
            if (searchResultsSection) searchResultsSection.classList.remove('active');
            
            const targetElement = document.getElementById(result.id);
            if (targetElement) {
                highlightElement(targetElement);
            }
        });
        
        resultActions.appendChild(resultLink);
        
        resultItem.append(resultImageContainer, resultInfo, resultActions);
        container.appendChild(resultItem);
    });
}

// === Funciones de Historial y Sugerencias ===

function saveSearchHistory() {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory));
}

export function addToHistory(term) {
    searchHistory = searchHistory.filter(item => item !== term);
    searchHistory.unshift(term);
    searchHistory = searchHistory.slice(0, 10);
    saveSearchHistory();
}

function removeFromHistory(term) {
    searchHistory = searchHistory.filter(item => item !== term);
    saveSearchHistory();
    updateHistoryDisplay();
}

export function clearAllHistory() {
    const clearBtn = document.getElementById('clear-all-history');
    if (clearBtn) {
        clearBtn.style.transform = 'scale(0.95)';
        clearBtn.style.opacity = '0.7';
        setTimeout(() => {
            clearBtn.style.transform = '';
            clearBtn.style.opacity = '';
        }, 150);
    }
    
    searchHistory = [];
    saveSearchHistory();
    updateHistoryDisplay();
    
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    const searchInput = document.getElementById('search-input');
    if (suggestionsDropdown && suggestionsDropdown.classList.contains('active') && searchInput) {
        const query = searchInput.value.trim();
        if (!query || filterSuggestions(query).length === 0) {
            suggestionsDropdown.classList.remove('active');
        }
    }
}

function filterSuggestions(query) {
    if (!query || query.length < 1) return [];
    const lowerQuery = query.toLowerCase();
    return searchSuggestions.filter(suggestion => 
        suggestion.text.toLowerCase().includes(lowerQuery)
    ).slice(0, 6);
}

function createSuggestionElement(suggestion, isHistory = false) {
    const item = document.createElement('div');
    item.className = 'suggestion-item';
    
    if (isHistory) {
        item.innerHTML = `
            <i class="suggestion-icon fas fa-history"></i>
            <span class="suggestion-text">${suggestion}</span>
            <i class="history-remove fas fa-times" data-term="${suggestion}"></i>
        `;
    } else {
        item.innerHTML = `
            <i class="suggestion-icon ${suggestion.icon}"></i>
            <span class="suggestion-text">${suggestion.text}</span>
            <span class="suggestion-type">${suggestion.type}</span>
        `;
    }
    return item;
}

function updateSuggestionsDisplay(query) {
    const suggestionsList = document.getElementById('suggestions-list');
    if (!suggestionsList) return;
    suggestionsList.innerHTML = '';
    
    if (!query || query.length < 1) return;

    filteredSuggestions = filterSuggestions(query);
    
    filteredSuggestions.forEach((suggestion) => {
        const item = createSuggestionElement(suggestion);
        item.addEventListener('click', () => {
            selectSuggestion(suggestion.text);
        });
        suggestionsList.appendChild(item);
    });
}

export function updateHistoryDisplay() {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;
    historyList.innerHTML = '';
    
    searchHistory.slice(0, 5).forEach(term => {
        const item = createSuggestionElement(term, true);
        
        item.addEventListener('click', (e) => {
            if (!e.target.classList.contains('history-remove')) {
                selectSuggestion(term);
            }
        });
        
        const removeBtn = item.querySelector('.history-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                removeFromHistory(term);
            });
        }
        
        historyList.appendChild(item);
    });
}

function selectSuggestion(text) {
    const searchInput = document.getElementById('search-input');
    const searchForm = document.getElementById('search-form');
    if (searchInput) {
        searchInput.value = text;
        hideSuggestions();
        if (searchForm) searchForm.dispatchEvent(new Event('submit'));
    }
}

function showSuggestions() {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (suggestionsDropdown) {
        updateHistoryDisplay();
        suggestionsDropdown.classList.add('active');
    }
}

export function hideSuggestions() {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (suggestionsDropdown) {
        suggestionsDropdown.classList.remove('active');
        currentSuggestionIndex = -1;
        clearHighlight();
    }
}

function clearHighlight() {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (suggestionsDropdown) {
        const highlighted = suggestionsDropdown.querySelectorAll('.suggestion-item.highlighted');
        highlighted.forEach(item => item.classList.remove('highlighted'));
    }
}

function highlightSuggestion(index) {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (!suggestionsDropdown) return;
    clearHighlight();
    const allItems = suggestionsDropdown.querySelectorAll('.suggestion-item');
    if (allItems[index]) {
        allItems[index].classList.add('highlighted');
        allItems[index].scrollIntoView({ block: 'nearest' });
    }
}

function navigateWithKeyboard(direction) {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (!suggestionsDropdown) return;
    const allItems = suggestionsDropdown.querySelectorAll('.suggestion-item');
    const totalItems = allItems.length;
    
    if (totalItems === 0) return;
    
    if (direction === 'down') {
        currentSuggestionIndex = (currentSuggestionIndex + 1) % totalItems;
    } else if (direction === 'up') {
        currentSuggestionIndex = currentSuggestionIndex <= 0 ? totalItems - 1 : currentSuggestionIndex - 1;
    }
    
    highlightSuggestion(currentSuggestionIndex);
}

function selectHighlightedSuggestion() {
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    if (!suggestionsDropdown) return;
    const highlighted = suggestionsDropdown.querySelector('.suggestion-item.highlighted');
    if (highlighted) {
        const text = highlighted.querySelector('.suggestion-text').textContent;
        selectSuggestion(text);
    }
}

// Inicialización
export function initSearch() {
    const searchInput = document.getElementById('search-input');
    const searchForm = document.getElementById('search-form');
    const suggestionsDropdown = document.getElementById('search-suggestions-dropdown');
    const clearAllHistoryBtn = document.getElementById('clear-all-history');
    
    refreshSearchableItems();

    if (searchInput && suggestionsDropdown) {
        searchInput.addEventListener('focus', () => {
            showSuggestions();
        });

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                updateSuggestionsDisplay(query);
                if (query.length > 0) {
                    showSuggestions();
                }
            }, 150);
        });

        searchInput.addEventListener('keydown', (e) => {
            if (!suggestionsDropdown.classList.contains('active')) return;
            
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    navigateWithKeyboard('down');
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    navigateWithKeyboard('up');
                    break;
                case 'Enter':
                    if (currentSuggestionIndex >= 0) {
                        e.preventDefault();
                        selectHighlightedSuggestion();
                    }
                    break;
                case 'Escape':
                    hideSuggestions();
                    searchInput.blur();
                    break;
            }
        });
    }

    if (clearAllHistoryBtn) {
        clearAllHistoryBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            clearAllHistory();
        });
    }

    if (suggestionsDropdown) {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-container')) {
                hideSuggestions();
            }
        });
    }

    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const searchTerm = searchInput.value.trim();
            const skipHistory = searchForm?.dataset?.skipHistory === 'true';
            
            if (searchTerm) {
                if (!skipHistory) {
                    addToHistory(searchTerm);
                }
                hideSuggestions();
                
                const results = performSearch(searchTerm, searchableItems);
                const resultsContainer = document.getElementById('results-container');
                const searchResultsSection = document.querySelector('.search-results');
                
                if (resultsContainer && searchResultsSection) {
                    displayResults(results, searchTerm, resultsContainer);
                    searchResultsSection.classList.add('active');
                }
            }
            
            if (skipHistory) {
                delete searchForm.dataset.skipHistory;
            }
        });
    }
    
    updateHistoryDisplay();
}
