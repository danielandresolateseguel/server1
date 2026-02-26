/**
 * Checkout and WhatsApp Logic
 */
import { cart, clearCart } from './cart.js';
import { closeCartUI } from './ui.js';
import { getWhatsappNumber, CATEGORY, getCheckoutMode, getWhatsappEnabled, getWhatsappTemplate, getBusinessSlug } from './config.js';

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
    const deliveryName = (document.getElementById('delivery-name')?.value || '').trim();
    const esperaName = (document.getElementById('espera-name')?.value || '').trim();
    const esperaPhone = (document.getElementById('espera-phone')?.value || '').trim();
    const orderNotes = (document.getElementById('order-notes')?.value || '').trim();

    // Validaciones
    if (orderType === 'mesa' && !mesaNumber) { alert('Por favor, ingresa el número de mesa.'); return; }
    if (orderType === 'direccion') {
        if (!address) { alert('Por favor, ingresa la dirección de entrega.'); return; }
        if (!contactPhone) { alert('Por favor, ingresa el teléfono de contacto.'); return; }
        if (!deliveryName) { alert('Por favor, ingresa tu nombre.'); return; }
    }
    if (orderType === 'espera') {
        if (!esperaName) { alert('Por favor, ingresa tu nombre.'); return; }
        if (!esperaPhone) { alert('Por favor, ingresa tu teléfono.'); return; }
    }

    // Construcción del mensaje (Nueva Lógica con Template)
    // 1. Prepare Data Strings
    let pedidoInfo = '';
    if (orderType === 'mesa') pedidoInfo = `\uD83D\uDCCD Modalidad: Mesa\n   \uD83C\uDF7D Mesa N°: ${mesaNumber}`;
    else if (orderType === 'direccion') pedidoInfo = `\uD83D\uDCCD Modalidad: Dirección\n   \uD83C\uDFE0 Dirección: ${address}\n   \uD83D\uDC64 Nombre: ${deliveryName}`;
    else if (orderType === 'espera') pedidoInfo = `\uD83D\uDCCD Modalidad: Espera en local\n   \uD83D\uDC64 Nombre: ${esperaName}\n   \uD83D\uDCDE Teléfono: ${esperaPhone}`;

    let itemsList = '';
    cart.forEach((item, index) => {
        const precioFormateado = '$' + parseInt(item.price).toLocaleString('es-AR') + ' ARS';
        itemsList += `${index + 1}. \uD83D\uDCE6 ${item.name}\n`;
        itemsList += `   \uD83D\uDCCA Cantidad: ${item.quantity}\n`;
        itemsList += `   \uD83D\uDCB5 Precio unitario: ${precioFormateado}\n`;
        itemsList += `   \uD83D\uDCB0 Subtotal: $${parseInt(item.price * item.quantity).toLocaleString('es-AR')} ARS\n`;
        if ((item.notes || '').trim()) itemsList += `   \uD83D\uDCDD Detalle: ${(item.notes||'').trim()}\n`;
        itemsList += '\n';
    });

    // Totals logic
    let shippingCost = 0;
    if (orderType === 'direccion' && window.BusinessConfig && window.BusinessConfig.shipping_cost) {
        shippingCost = parseInt(window.BusinessConfig.shipping_cost) || 0;
    }
    const totalNumber = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0) + shippingCost;
    const totalText = '$' + parseInt(totalNumber).toLocaleString('es-AR') + ' ARS';
    const currentCategory = (CATEGORY || '').toLowerCase();
    const isCommerce = currentCategory === 'comercio' || currentCategory === 'general';

    let totales = '';
    if (shippingCost > 0) {
        totales += `\uD83D\uDE9A Costo de envío: $${shippingCost.toLocaleString('es-AR')} ARS\n`;
    }
    
    if (isCommerce) {
        totales += `\uD83D\uDCB0 TOTAL: ${totalText}\n`;
    } else {
        totales += `\uD83D\uDCB0 TOTAL (sin propina): ${totalText}\n`;
    }

    if (orderType === 'mesa') {
        const tip = Math.round(totalNumber * 0.10);
        totales += `\uD83D\uDC81 Propina sugerida (10%): $${parseInt(tip).toLocaleString('es-AR')} ARS\n`;
        totales += `\uD83C\uDF7D\uFE0F TOTAL con propina sugerida: $${parseInt(totalNumber + tip).toLocaleString('es-AR')} ARS\n`;
    }

    let notas = '';
    if (orderNotes) notas = `\uD83D\uDCDD Detalle adicional: ${orderNotes}`;

    // 2. Get Template
    let template = getWhatsappTemplate();
    if (!template) {
        // Fallback default template
        template = `¡Hola! \uD83D\uDC4B Espero que estés muy bien.

\uD83D\uDED2 Me gustaría realizar el siguiente pedido:

{PEDIDO_INFO}

{ITEMS}

{TOTALES}

{NOTAS}

`;
        if (orderType !== 'mesa') template += '¿Podrías confirmarme la disponibilidad y el método de entrega?\n\n';
        if (isCommerce) template += '¿Qué métodos de pago aceptan? (efectivo, débito, crédito, transferencia)\n\n';
        template += '¡Muchas gracias! \uD83D\uDE0A';
    }

    // 3. Construct Final Message
    let mensaje = template
        .replace('{PEDIDO_INFO}', pedidoInfo)
        .replace('{ITEMS}', itemsList)
        .replace('{TOTALES}', totales)
        .replace('{NOTAS}', notas);

    // SANITIZATION: Check for corruption (diamonds) and fallback if necessary
    if (mensaje.indexOf('\ufffd') !== -1) {
        console.warn('Corrupt template detected (diamonds). Using fallback.');
        mensaje = `¡Hola! \uD83D\uDC4B Espero que estés muy bien.

\uD83D\uDED2 Me gustaría realizar el siguiente pedido:

${pedidoInfo}

${itemsList}

${totales}

${notas}`;
    }

    // cleanup multiple newlines
    mensaje = mensaje.replace(/\n{3,}/g, '\n\n').trim();

    // 4. Send to WhatsApp (Use api.whatsapp.com directly to avoid redirect encoding issues)
    if (getWhatsappEnabled()) {
        const urlWhatsApp = `https://api.whatsapp.com/send?phone=${getWhatsappNumber().replace('+', '')}&text=${encodeURIComponent(mensaje)}`;
        window.open(urlWhatsApp, '_blank');
    }

    // Enviar al backend (background)
    sendOrderToBackend(orderType, { mesaNumber, address, contactPhone, esperaName, esperaPhone, deliveryName, orderNotes }, totalNumber);

    // Vaciar carrito tras iniciar proceso de pedido
    clearCart();
    
    // Cerrar UI del carrito
    closeCartUI();
}

function sendOrderToBackend(orderType, data, total) {
    try {
        const getTenantSlug = () => {
            let slug = getBusinessSlug();
            const alias = {
                'gatrolocal1': 'gastronomia-local1',
                'gastro-local1': 'gastronomia-local1',
                'gastro1': 'gastronomia-local1'
            };
            slug = alias[slug] || slug || 'gastronomia-local1';
            return slug;
        };

        const payload = {
            tenant_slug: getTenantSlug(),
            order_type: orderType,
            table_number: orderType === 'mesa' ? data.mesaNumber : '',
            address: orderType === 'direccion' ? { address: data.address } : {},
            customer_phone: orderType === 'direccion' ? data.contactPhone : (orderType === 'espera' ? data.esperaPhone : ''),
            customer_name: orderType === 'espera' ? data.esperaName : (orderType === 'direccion' ? data.deliveryName : ''),
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
        .catch(err => {
            console.error('Error enviando orden al backend:', err);
            alert('Hubo un error al registrar el pedido en el sistema. Por favor, avisa al personal.');
        });
    } catch (e) {
        console.error('Error preparando envío al backend:', e);
        alert('Error preparando el pedido. Intenta nuevamente.');
    }
}
