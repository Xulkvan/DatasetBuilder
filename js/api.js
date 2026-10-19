// @ts-check
// V11.5.0: Extracted API Layer
/**
 * @param {string} url
 * @param {RequestInit & {headers?: Record<string,string>}} [opts]
 * @returns {Promise<any>}
 */
export async function api(url, opts) {
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    const h = new Headers(opts.headers || {});
    h.set('X-Requested-With', 'DatasetBuilder');
    opts = { ...opts, headers: h };
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      const d = data && data.detail;
      if (typeof d === 'string') detail = d;
      else if (d && typeof d === 'object' && !Array.isArray(d) && d.key) {
        const translated = (typeof window.t === 'function') ? window.t(d.key, d.params || {}) : null;
        detail = (translated && translated !== d.key) ? translated : (d.fallback || d.key);
      }
      else if (Array.isArray(d)) {
        detail = d.map(x => {
          if (typeof x === 'string') return x;
          if (x && typeof x === 'object' && x.key) {
            const tr = (typeof window.t === 'function') ? window.t(x.key, x.params || {}) : null;
            return (tr && tr !== x.key) ? tr : (x.fallback || x.key);
          }
          if (x && typeof x === 'object') return x.msg || x.message || JSON.stringify(x);
          return String(x);
        }).join('; ');
      } else if (d && typeof d === 'object') {
        detail = d.msg || d.message || JSON.stringify(d);
      }
    } catch (e) {}
    const err = new Error(detail || res.statusText);
    err.status = res.status; err.detail = detail;
    throw err;
  }
  return res.json();
}

/**
 * @param {string} url
 * @param {string} fallbackName
 * @returns {Promise<void>}
 */
export async function downloadFile(url, fallbackName) {
  try {
    window.setStatus(window.t('toast.downloading'), 60000);
    const res = await fetch(url);
    if (!res.ok) {
      let msg = 'Ошибка экспорта';
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    const name = m ? m[1] : fallbackName;
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(objUrl); a.remove(); }, 1000);
    window.setSuccess('Скачано: ' + name, 4000);
  } catch (e) { window.setError('Ошибка экспорта: ' + String(e.message).slice(0, 160)); }
}
