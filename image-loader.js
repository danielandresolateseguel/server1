// Script para optimización de imágenes
document.addEventListener('DOMContentLoaded', function() {
    // IntersectionObserver para marcar imágenes como cargadas al entrar en el viewport
    function setupIntersectionObserver() {
        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        if (!img.dataset.loaded) {
                            img.dataset.loaded = true;
                            img.classList.add('loaded');
                        }
                        observer.unobserve(img);
                    }
                });
            }, { rootMargin: '600px 0px', threshold: 0.01 });

            document.querySelectorAll('img[loading="lazy"]').forEach(img => observer.observe(img));

            // Observar nuevas imágenes añadidas dinámicamente
            const mo = new MutationObserver((mutations) => {
                mutations.forEach(m => {
                    m.addedNodes && m.addedNodes.forEach(node => {
                        if (node && node.nodeType === 1) {
                            if (node.tagName === 'IMG' && node.getAttribute('loading') === 'lazy') {
                                observer.observe(node);
                            }
                            const imgs = node.querySelectorAll ? node.querySelectorAll('img[loading="lazy"]') : [];
                            imgs.forEach(img => observer.observe(img));
                        }
                    });
                });
            });
            mo.observe(document.body, { childList: true, subtree: true });
        } else {
            // Fallback: verificar en scroll/resize para navegadores sin IO
            function isInViewport(element) {
                const rect = element.getBoundingClientRect();
                return rect.top < (window.innerHeight || document.documentElement.clientHeight) && rect.bottom > 0;
            }
            function lazyLoadFallback() {
                const images = document.querySelectorAll('img[loading="lazy"]');
                images.forEach(img => {
                    if (isInViewport(img) && !img.dataset.loaded) {
                        img.dataset.loaded = true;
                        img.classList.add('loaded');
                    }
                });
            }
            window.addEventListener('scroll', lazyLoadFallback);
            window.addEventListener('resize', lazyLoadFallback);
            lazyLoadFallback();
        }
    }

    // Función para manejar errores de carga de imágenes
    function handleImageError() {
        const images = document.querySelectorAll('img');

        images.forEach(img => {
            function fallbackIfReallyBroken() {
                // Si la imagen ya cargó correctamente, no hacer nada
                if (img.complete && img.naturalWidth > 0) return;
                // Reemplazar con imagen local de respaldo si realmente falla la carga/decodificación
                img.src = 'Imagenes/asus-proart-p16.png';
                img.alt = 'Imagen no disponible';
                // Evitar bucles de error únicamente después de aplicar el fallback
                img.onerror = null;
            }

            img.addEventListener('error', fallbackIfReallyBroken);
        });
    }

    // Fallback para navegadores sin soporte WebP
    function canUseWebp() {
        try {
            return document.createElement('canvas').toDataURL('image/webp').indexOf('data:image/webp') === 0;
        } catch (e) {
            return false;
        }
    }

    // Función para aplicar srcset a imágenes responsivas
    function setupResponsiveImages(root = document) {
        const productImages = root.querySelectorAll ? root.querySelectorAll('.product-image img') : [];
        productImages.forEach(img => {
            const src = img.getAttribute('src');
            if (src && !src.includes('placeholder')) {
                img.setAttribute('srcset', src);
            }
        });
    }

    // Aumentar prioridad de imágenes cercanas al fold
    function boostAboveFoldPriorities() {
        const viewportH = window.innerHeight || document.documentElement.clientHeight;
        const margin = 150; // adelanta un poco la descarga
        const candidates = document.querySelectorAll('.product-image img');
        candidates.forEach(img => {
            const rect = img.getBoundingClientRect();
            if (rect.top < viewportH + margin) {
                img.setAttribute('fetchpriority', 'high');
            }
        });
    }

    // Inicializar funciones
    setupIntersectionObserver();
    boostAboveFoldPriorities();
    handleImageError();
    setupResponsiveImages();

    // Watchdog: reemplazar imágenes que no decodifican tras carga
    function setupDecodeWatchdog() {
        const FALLBACK_SRC = 'Imagenes/asus-proart-p16.png';
        const applyWatchdog = (img) => {
            function ensureVisible() {
                if (img.complete && img.naturalWidth === 0) {
                    img.src = FALLBACK_SRC;
                    img.srcset = FALLBACK_SRC;
                    img.alt = img.alt || 'Imagen no disponible';
                }
            }
            img.addEventListener('load', ensureVisible);
        };
        document.querySelectorAll('.product-image img').forEach(applyWatchdog);
        const mo = new MutationObserver((mutations) => {
            mutations.forEach(m => {
                m.addedNodes && m.addedNodes.forEach(node => {
                    if (node && node.nodeType === 1) {
                        if (node.tagName === 'IMG' && node.closest('.product-image')) {
                            applyWatchdog(node);
                        }
                        const imgs = node.querySelectorAll ? node.querySelectorAll('.product-image img') : [];
                        imgs.forEach(applyWatchdog);
                    }
                });
            });
        });
        mo.observe(document.body, { childList: true, subtree: true });
        setTimeout(() => {
            document.querySelectorAll('.product-image img').forEach(img => {
                if (img.complete && img.naturalWidth === 0) {
                    img.src = FALLBACK_SRC;
                    img.srcset = FALLBACK_SRC;
                    img.alt = img.alt || 'Imagen no disponible';
                }
            });
        }, 1500);
    }
    setupDecodeWatchdog();

    // Aplicar fallback si el navegador no soporta WebP
    if (!canUseWebp()) {
        document.querySelectorAll('.product-image img').forEach(img => {
            const src = img.getAttribute('src') || '';
            if (src.toLowerCase().endsWith('.webp')) {
                img.setAttribute('src', 'Imagenes/asus-proart-p16.png');
                img.setAttribute('srcset', 'Imagenes/asus-proart-p16.png');
            }
        });
    }

    // Asegurar que la imagen de modal no se demore
    const modalImage = document.getElementById('modal-product-image');
    if (modalImage) {
        try {
            modalImage.decoding = 'async';
            modalImage.setAttribute('loading', 'eager');
            modalImage.setAttribute('fetchpriority', 'high');
        } catch (e) {
            // silencioso
        }
    }

    // Hook global para reinicializar con contenido dinámico
    window.__reinitImageLoader = function(rootEl) {
        const root = rootEl || document;
        setupResponsiveImages(root);
        boostAboveFoldPriorities(root);
        // Los observadores por mutación ya asegurarán IO y watchdog
    };
});