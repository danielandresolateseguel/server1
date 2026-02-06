// Lazy Loading Fase 1: prioridades y decodificación
document.addEventListener('DOMContentLoaded', function() {
  try {
    // Ajustar imágenes de productos
    const productImages = document.querySelectorAll('.product-image img');
    productImages.forEach(img => {
      img.decoding = 'async';
      img.setAttribute('fetchpriority', 'low');
      const src = img.getAttribute('src');
      if (src && !src.includes('placeholder')) {
        img.setAttribute('srcset', src);
      }
    });

    // Ajustar prioridades del carrusel
    const carouselImages = document.querySelectorAll('.carousel-slides .carousel-slide img');
    if (carouselImages.length) {
      carouselImages.forEach((img, idx) => {
        img.decoding = 'async';
        if (idx === 0) {
          img.setAttribute('loading', 'eager');
          img.setAttribute('fetchpriority', 'high');
        } else {
          img.setAttribute('loading', 'lazy');
          img.setAttribute('fetchpriority', 'low');
        }
      });
    }
  } catch (e) {
    console.warn('Lazy Fase 1: ajuste de prioridades falló', e);
  }
});