/**
 * Checkout and WhatsApp Logic
 */
import { cart, clearCart } from './cart.js';
import { closeCartUI } from './ui.js';
import { getWhatsappNumber, CATEGORY, getCheckoutMode } from './config.js';

export function handleCheckout() {
    if (cart.length === 0) {
        alert('Tu carrito está vacío');
        return;
    }

    const CHECKOUT_MODE = getCheckoutMode();
    const orderTypeEl = document.querySelector('input[name="orderType"]:checked');
    const orderType = orderTypeEl ? orderTypeEl.value : (CHECKOUT_MODE === 'mesa' ? 'mesa' : 'none');
    
    const mesaNumber = (document.getElementById('mesa-number')?.value || '').trim();
    const address = (document.getElementById('delivery-address')?.value || '').trim();
    const contactPhone = (document.getElementById('contact-phone')?.value || '').trim();
    const esperaName = (document.getElementById('espera-name')?.value || '').trim();
    const esperaPhone = (document.getElementById('espera-phone')?.value || '').trim();
    const orderNotes = (document.getElementById('order-notes')?.value || '').trim();

    // Validaciones
    if (orderType === 'mesa' && !mesaNumber) { alert('Por favor, ingresa el número de mesa.'); return; }
    if (orderType === 'direccion') {
        if (!address) { alert('Por favor, ingresa la dirección de entrega.'); return; }
        if (!contactPhone) { alert('Por favor, ingresa el teléfono de contacto.'); return; }
    }
    if (orderType === 'espera') {
        if (!esperaName) { alert('Por favor, ingresa tu nombre.'); return; }
        if (!esperaPhone) { alert('Por favor, ingresa tu teléfono.'); return; }
    }

    // Construcción del mensaje
    let mensaje = '¡Hola! 👋 Espero que estés muy bien.\n\n';
    mensaje += '🛒 Me gustaría realizar el siguiente pedido:\n\n';

    if (orderType === 'mesa') mensaje += `📍 Modalidad: Mesa\n   🪑 Mesa N°: ${mesaNumber}\n\n`;
    else if (orderType === 'direccion') mensaje += `📍 Modalidad: Dirección\n   🏠 Dirección: ${address}\n\n`;
    else if (orderType === 'espera') mensaje += `📍 Modalidad: Espera en local\n   👤 Nombre: ${esperaName}\n   📞 Teléfono: ${esperaPhone}\n\n`;

    cart.forEach((item, index) => {
        const precioFormateado = '$' + parseInt(item.price).toLocaleString('es-AR') + ' ARS';
        mensaje += `${index + 1}. 📦 ${item.name}\n`;
        mensaje += `   📊 Cantidad: ${item.quantity}\n`;
        mensaje += `   💵 Precio unitario: ${precioFormateado}\n`;
        mensaje += `   💰 Subtotal: $${parseInt(item.price * item.quantity).toLocaleString('es-AR')} ARS\n`;
        if ((item.notes || '').trim()) mensaje += `   📝 Detalle: ${(item.notes||'').trim()}\n`;
        mensaje += '\n';
    });

    let shippingCost = 0;
    if (orderType === 'direccion' && window.BusinessConfig && window.BusinessConfig.shipping_cost) {
        shippingCost = parseInt(window.BusinessConfig.shipping_cost) || 0;
    }
    if (shippingCost > 0) {
        mensaje += `🚚 Costo de envío: $${shippingCost.toLocaleString('es-AR')} ARS\n`;
    }

    const totalNumber = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0) + shippingCost;
    const totalText = '$' + parseInt(totalNumber).toLocaleString('es-AR') + ' ARS';
    
    const currentCategory = (CATEGORY || '').toLowerCase();
    const isCommerce = currentCategory === 'comercio' || currentCategory === 'general';
    
    if (isCommerce) {
        mensaje += `💰 TOTAL: ${totalText}\n\n`;
    } else {
        mensaje += `💰 TOTAL (sin propina): ${totalText}\n`;
    }

    if (orderType === 'mesa') {
        const tip = Math.round(totalNumber * 0.10);
        mensaje += `💁 Propina sugerida (10%): $${parseInt(tip).toLocaleString('es-AR')} ARS\n`;
        mensaje += `🍽️ TOTAL con propina sugerida: $${parseInt(totalNumber + tip).toLocaleString('es-AR')} ARS\n\n`;
    } else {
        mensaje += `\n`;
    }

    if (orderNotes) mensaje += `📝 Detalle adicional: ${orderNotes}\n\n`;
    if (orderType !== 'mesa') mensaje += '¿Podrías confirmarme la disponibilidad y el método de entrega?\n\n';
    if (isCommerce) mensaje += '¿Qué métodos de pago aceptan? (efectivo, débito, crédito, transferencia)\n\n';
    
    mensaje += '¡Muchas gracias! 😊';

    // Enviar a WhatsApp
    const urlWhatsApp = `https://wa.me/${getWhatsappNumber()}?text=${encodeURIComponent(mensaje)}`;
    window.open(urlWhatsApp, '_blank');

    // Enviar al backend (background)
    sendOrderToBackend(orderType, { mesaNumber, address, contactPhone, esperaName, esperaPhone, orderNotes }, totalNumber);

    // Vaciar carrito tras iniciar proceso de pedido
    clearCart();
    
    // Cerrar UI del carrito
    closeCartUI();
}

function sendOrderToBackend(orderType, data, total) {
    try {
        const getTenantSlug = () => {
            const dataSlug = document.body.dataset.tenant ? document.body.dataset.tenant.trim() : '';
            if (dataSlug) return dataSlug;
            try {
                const name = (window.location.pathname.split('/').pop() || '').replace(/\.html$/,'');
                return name || 'gastronomia-local1';
            } catch (_) { return 'gastronomia-local1'; }
        };

        const payload = {
            tenant_slug: getTenantSlug(),
            order_type: orderType,
            table_number: orderType === 'mesa' ? data.mesaNumber : '',
            address: orderType === 'direccion' ? { address: data.address } : {},
            customer_phone: orderType === 'direccion' ? data.contactPhone : (orderType === 'espera' ? data.esperaPhone : ''),
            customer_name: orderType === 'espera' ? data.esperaName : '',
            items: cart.map(it => ({ id: it.id, name: it.name, price: it.price, quantity: it.quantity, notes: it.notes || '' })),
            order_notes: data.orderNotes
        };

        const API_BASE = window.location.origin;
        fetch(new URL('/api/orders', API_BASE).toString(), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.order_id) {
                console.log('Orden creada con ID:', data.order_id);
                const slug = getTenantSlug();
                localStorage.setItem('last_order_id_' + slug, data.order_id);
                localStorage.setItem('last_viewed_status_' + slug, 'pending'); // Reset status tracking
            }
        })
        .catch(err => console.error('Error enviando orden al backend:', err));
    } catch (e) {
        console.error('Error preparando envío al backend:', e);
    }
}
