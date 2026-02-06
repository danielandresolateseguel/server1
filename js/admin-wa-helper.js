/**
 * WhatsApp and Address Helpers for Admin Panel
 * Extracted to external file to ensure proper encoding and caching.
 */

function getAddressText(val) {
  try {
    if (val && typeof val === 'object') return String(val.address || val.street || val.line1 || '').trim();
    const raw = String(val || '').trim();
    if (!raw) return '';
    if (raw.startsWith('{')) {
      try {
        const j = JSON.parse(raw);
        return String(j.address || j.street || j.line1 || '').trim();
      } catch (_) {
        try {
           // Try replacing single quotes with double quotes for Python-style dict strings
           const fixed = raw.replace(/'/g, '"');
           const j = JSON.parse(fixed);
           return String(j.address || j.street || j.line1 || '').trim();
        } catch(__) {}
      }
    }
    // Fallback regex for tricky formats
    if (raw.includes('address') || raw.includes('calle')) {
       const match = raw.match(/['"]?(?:address|street|line1)['"]?\s*[:=]\s*['"]([^'"]+)['"]/i);
       if (match && match[1]) return match[1].trim();
    }
    return raw;
  } catch (_) {
    return String(val || '').trim();
  }
}

function destinoLabelFor(order) {
  if (order.order_type === 'mesa') return `Mesa ${order.table_number || ''}`;
  if (order.order_type === 'espera') return `Espera: ${order.customer_name || ''}`;
  return getAddressText(order.address_json).replace(/\n+/g,' ').slice(0,64);
}

function getWaLink(order, phoneDigits) {
  if (!phoneDigits) return '';
  let tenantName = 'Nuestro Local';
  const tInput = document.getElementById('tenant-input');
  if (tInput && tInput.value) {
    // Formatea slug: "gastronomia-local1" -> "Gastronomia Local 1"
    tenantName = tInput.value
        .replace(/-/g, ' ')
        .replace(/(\d+)/g, ' $1')
        .trim()
        .replace(/\b\w/g, c => c.toUpperCase());
  }
  const isDireccion = (String(order.order_type || '').toLowerCase() === 'direccion');
  const address = isDireccion ? getAddressText(order.address_json) : '';
  const cName = (order.customer_name || '').trim();
  
  // Use escaped unicode for emojis to ensure safety
  // \uD83D\uDC4B = Waving Hand
  // \uD83D\uDCCD = Pushpin
  const waveEmoji = '\uD83D\uDC4B'; 
  const pinEmoji = '\uD83D\uDCCD';

  let msg = `Hola${cName ? ' ' + cName : ''}! ${waveEmoji} Te escribimos de *${tenantName}* por tu pedido *#${order.id}*.`;
  if (address) {
    msg += ` ${pinEmoji} Dirección de entrega: ${address}.`;
  }

  // SANITIZATION: Check for corruption (diamonds) in inputs
  if (msg.indexOf('\ufffd') !== -1) {
      console.warn('Diamond char detected in WA link, stripping...');
      msg = msg.replace(/\ufffd/g, '');
  }

  // // console.log('WA Link generated (v3):', msg); // Debug log

  return `https://api.whatsapp.com/send?phone=${phoneDigits}&text=${encodeURIComponent(msg)}`;
}
