// Aplica variables de tema para páginas de gastronomía usando data-theme
// Lee config/gastronomia.json -> themes[theme].palette y setea CSS variables

(function () {
  function hexToRgb(hex) {
    const clean = hex.replace('#', '');
    const bigint = parseInt(clean.length === 3
      ? clean.split('').map(c => c + c).join('')
      : clean, 16);
    const r = (bigint >> 16) & 255;
    const g = (bigint >> 8) & 255;
    const b = bigint & 255;
    return { r, g, b };
  }

  function rgbaString({ r, g, b }, alpha) {
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  async function applyTheme() {
    const body = document.body;
    const page = body.dataset.page;
    const theme = body.dataset.theme;
    const slug = (window.BUSINESS_SLUG || (body.dataset && body.dataset.slug) || 'gastronomia');

    if (page !== 'gastronomia' || !theme) return;

    try {
      const res = await fetch(`config/${slug}.json`, { cache: 'no-store' });
      const cfg = await res.json();
      const themeCfg = cfg.themes && cfg.themes[theme];
      if (!themeCfg || !themeCfg.palette) return;

      const p = themeCfg.palette;
      const accentRgb = hexToRgb(p.accent);

      body.style.setProperty('--gastro-accent', p.accent);
      body.style.setProperty('--gastro-accent-dark', p.accentDark || p.accent);
      body.style.setProperty('--gastro-chip-bg', p.chipBg);
      body.style.setProperty('--gastro-chip-hover-bg', p.chipHoverBg || p.chipBg);
      body.style.setProperty('--gastro-chip-text', p.chipText || '#111111');
      body.style.setProperty('--gastro-surface-card', p.surfaceCard || '#ffffff');

      // Derivados del acento con alpha, usados en bordes y sombras
      const alphas = [0.08, 0.18, 0.22, 0.25, 0.28, 0.35, 0.42, 0.55, 0.85];
      for (const a of alphas) {
        body.style.setProperty(`--gastro-accent-${String(a).replace('.', '')}`, rgbaString(accentRgb, a));
      }

      // Fondos y gradientes por sección (opcionales). Si existen en config, se aplican.
      const bg = themeCfg.backgrounds || {};
      const map = {
        page: '--gastro-page-bg',
        specialDiscounts: '--gastro-special-discounts-bg',
        productsSection: '--gastro-products-bg',
        interestSection: '--gastro-interest-bg',
        carousel: '--gastro-carousel-bg',
        cartHeader: '--gastro-cart-header-bg',
        floatingCart: '--gastro-floating-cart-bg',
        restaurantInfo: '--gastro-restaurant-bg',
        footer: '--gastro-footer-bg'
      };
      for (const key in map) {
        if (Object.prototype.hasOwnProperty.call(bg, key) && bg[key]) {
          body.style.setProperty(map[key], bg[key]);
        }
      }

      body.setAttribute('data-theme-loaded', 'true');
    } catch (e) {
      // Silencioso para no romper la UI si falla
      console.warn('theme-loader: no se pudo aplicar tema', e);
    }
  }

  // Branding para páginas de comercio: lee BusinessConfig.meta.branding y aplica CSS variables
  function applyCommerceBranding() {
    const body = document.body;
    const page = body.dataset.page;
    if (page !== 'comercio') return;

    // Si BusinessConfig no está listo, intentar cargar de forma defensiva desde config/<slug>.json
    let attemptedFetch = false;
    function ensureBusinessConfigLoaded() {
      try {
        if ((window.BusinessConfig && window.BusinessConfig.__loaded) || attemptedFetch) return;
        const slug = (window.BUSINESS_SLUG || (body.dataset && body.dataset.slug) || 'comercio');
        const url = `config/${slug}.json`;
        attemptedFetch = true;
        fetch(url).then(res => {
          if (!res.ok) throw new Error('No config JSON found');
          return res.json();
        }).then(json => {
          window.BusinessConfig = Object.assign({}, window.BusinessConfig || {}, json, { __loaded: true });
          document.dispatchEvent(new CustomEvent('businessconfig:ready'));
          console.info('theme-loader: BusinessConfig loaded (fallback) from', url);
        }).catch(() => {
          // silencioso: se usan defaults
        });
      } catch (_) {
        // silencioso
      }
    }

    const apply = () => {
      try {
        const cfg = window.BusinessConfig;
        const b = (cfg && cfg.meta && cfg.meta.branding) || {};
        const primary = b.primaryColor || '#1e88e5';
        const secondary = b.secondaryColor || '#4a6fa5';
        const titleColor = b.titleColor || '';
        const bg = b.backgroundColor || '';
        const text = b.textColor || '';
        const btnBg = b.buttonColor || primary;
        const btnText = b.buttonTextColor || '#ffffff';
        const border = b.borderColor || secondary;
        const catBg = b.categoryColor || '';
        const catText = b.categoryTextColor || '';
        const catBorder = b.categoryBorderColor || '';
        const catActiveText = b.categoryActiveTextColor || '';
        const catBaseBg = b.categoryBaseBg || '';
        const catHoverBg = b.categoryHoverBg || '';

        body.style.setProperty('--brand-primary', primary);
        body.style.setProperty('--brand-secondary', secondary);
        if (titleColor) {
          body.style.setProperty('--brand-title-color', titleColor);
        } else {
          // Si no se define, usar el color primario como título por defecto
          body.style.setProperty('--brand-title-color', primary);
        }
        if (bg) body.style.setProperty('--brand-bg', bg);
        if (text) body.style.setProperty('--brand-text', text);
        body.style.setProperty('--brand-button-bg', btnBg);
        body.style.setProperty('--brand-button-text', btnText);
        body.style.setProperty('--brand-border', border);
        // Categorías (chips / filtros)
        if (catBg) body.style.setProperty('--brand-category-bg', catBg); else body.style.removeProperty('--brand-category-bg');
        if (catText) body.style.setProperty('--brand-category-text', catText); else body.style.removeProperty('--brand-category-text');
        if (catBorder) body.style.setProperty('--brand-category-border', catBorder); else body.style.removeProperty('--brand-category-border');
        if (catActiveText) body.style.setProperty('--brand-category-active-text', catActiveText); else body.style.removeProperty('--brand-category-active-text');
        if (catBaseBg) body.style.setProperty('--brand-category-bg-base', catBaseBg); else body.style.removeProperty('--brand-category-bg-base');
        if (catHoverBg) body.style.setProperty('--brand-category-hover-bg', catHoverBg); else body.style.removeProperty('--brand-category-hover-bg');

        // Fondos por sección (opcionales) para comercio
        const backgrounds = (b && b.backgrounds) || {};
        const brandBgMap = {
          page: '--brand-page-bg',
          productsSection: '--brand-products-bg',
          interestSection: '--brand-interest-bg',
          specialDiscounts: '--brand-special-discounts-bg',
          modal: '--brand-modal-bg',
          footer: '--brand-footer-bg',
          // Nuevos fondos parametrizables para comercio
          cartHeader: '--brand-cart-header-bg',
          floatingCart: '--brand-floating-cart-bg',
          checkoutBtn: '--brand-checkout-btn-bg'
        };
        for (const key in brandBgMap) {
          if (Object.prototype.hasOwnProperty.call(backgrounds, key) && backgrounds[key]) {
            body.style.setProperty(brandBgMap[key], backgrounds[key]);
          } else {
            // Si no está definido en JSON, limpiar para que aplique el default de style.css
            body.style.removeProperty(brandBgMap[key]);
          }
        }

        // Texto específico para la sección Información de la Tienda
        if (b.storeInfoTextColor) {
          body.style.setProperty('--brand-store-info-text', b.storeInfoTextColor);
        } else {
          body.style.removeProperty('--brand-store-info-text');
        }

        // Texto del footer
        if (b.footerTextColor) {
          body.style.setProperty('--brand-footer-text', b.footerTextColor);
        } else {
          body.style.removeProperty('--brand-footer-text');
        }

        // Actualiza meta theme-color si existe
        const metaTheme = document.querySelector('meta[name="theme-color"]');
        if (metaTheme) metaTheme.setAttribute('content', primary);

        body.setAttribute('data-theme-loaded', 'true');
      } catch (e) {
        console.warn('theme-loader: no se pudo aplicar branding de comercio', e);
      }
    };

    if (window.BusinessConfig && window.BusinessConfig.__loaded) {
      apply();
    }
    else {
      // Intentar cargar config de forma defensiva y aplicar cuando esté lista
      ensureBusinessConfigLoaded();
    }
    document.addEventListener('businessconfig:ready', apply);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { applyTheme(); applyCommerceBranding(); });
  } else {
    applyTheme();
    applyCommerceBranding();
  }
})();