// Extract same-origin links and forms from server-rendered HTML captured by REA.
// Deliberately small: the runner only needs navigation targets and form fields, not a full DOM.

const STATIC = /\.(css|js|mjs|png|jpe?g|gif|svg|ico|woff2?|ttf|eot|map|pdf|zip)(\?|$)/i;
const STATIC_PREFIXES = ['/webjars/', '/resources/', '/static/', '/assets/', '/favicon'];

const decode = (value) => value
  .replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');

function attributes(tag) {
  const out = {};
  for (const match of tag.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
    const name = match[1].toLowerCase();
    if (name === tag.match(/^<\s*([a-zA-Z0-9]+)/)?.[1]?.toLowerCase()) continue;
    out[name] = decode(match[2] ?? match[3] ?? match[4] ?? '');
  }
  return out;
}

/** Resolve an href against the page; null when it leaves the origin or is not a page. */
export function pageUrl(href, base) {
  if (!href || /^(javascript|mailto|tel|data):/i.test(href) || href.startsWith('#')) return null;
  let url;
  try { url = new URL(href, base); } catch { return null; }
  if (url.origin !== new URL(base).origin) return null;
  if (STATIC.test(url.pathname) || STATIC_PREFIXES.some((p) => url.pathname.startsWith(p))) return null;
  url.hash = '';
  url.pathname = url.pathname.replace(/;jsessionid=[^/;?]*/gi, '');   // servlet session ids are not part of the route
  return url.toString();
}

export function links(html, base) {
  const found = new Set();
  for (const match of html.matchAll(/<a\b[^>]*>/gi)) {
    const href = attributes(match[0]).href;
    const url = pageUrl(href, base);
    if (url) found.add(url);
  }
  return [...found].sort();
}

function cssString(value) { return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"'); }

/** Forms with the fields a scenario must fill. Each field carries a CSS selector scoped to its form. */
export function forms(html, base) {
  const out = [];
  let index = 0;
  for (const match of html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/gi)) {
    const attrs = attributes(`<form ${match[1]}>`);
    const body = match[2];
    const action = pageUrl(attrs.action || base, base) || (attrs.action ? null : base);
    if (!action) { index += 1; continue; }
    // Playwright locators must resolve to one element: :nth-match picks the n-th form wherever it sits in the page.
    const scope = attrs.id ? `form#${cssString(attrs.id)}` : `:nth-match(form, ${index + 1})`;
    const fields = [];
    for (const input of body.matchAll(/<input\b[^>]*>/gi)) {
      const a = attributes(input[0]);
      const type = (a.type || 'text').toLowerCase();
      if (!a.name || ['hidden', 'submit', 'button', 'image', 'reset', 'file'].includes(type)) continue;
      fields.push({ kind: type === 'checkbox' || type === 'radio' ? type : 'input', type, name: a.name, required: 'required' in a, value: a.value ?? '',
        selector: `${scope} [name="${cssString(a.name)}"]` + (type === 'radio' ? `[value="${cssString(a.value ?? '')}"]` : '') });
    }
    for (const select of body.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/gi)) {
      const a = attributes(`<select ${select[1]}>`);
      if (!a.name) continue;
      const options = [...select[2].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/gi)]
        .map((o) => { const oa = attributes(`<option ${o[1]}>`); return 'value' in oa ? oa.value : o[2].trim(); })
        .filter((v) => v !== '');
      fields.push({ kind: 'select', type: 'select', name: a.name, required: 'required' in a, options, selector: `${scope} select[name="${cssString(a.name)}"]` });
    }
    for (const area of body.matchAll(/<textarea\b([^>]*)>/gi)) {
      const a = attributes(`<textarea ${area[1]}>`);
      if (a.name) fields.push({ kind: 'input', type: 'textarea', name: a.name, required: 'required' in a, value: '', selector: `${scope} textarea[name="${cssString(a.name)}"]` });
    }
    const explicit = /<(button|input)\b[^>]*type\s*=\s*["']?submit/i.test(body);
    const implicit = /<button\b(?![^>]*type\s*=)/i.test(body);
    const submit = explicit ? `:nth-match(${scope} [type="submit"], 1)` : implicit ? `:nth-match(${scope} button, 1)` : null;
    out.push({ index, id: attrs.id || null, method: (attrs.method || 'get').toUpperCase(), action, submit, fields });
    index += 1;
  }
  return out;
}

/** A stable shape for de-duplicating pages and forms: numeric path segments become {id}. */
export function routeShape(url) {
  const u = new URL(url);
  const path = u.pathname.replace(/;jsessionid=[^/;?]*/gi, '').split('/').map((s) => (/^\d+$/.test(s) ? '{id}' : s)).join('/');
  const query = [...u.searchParams.keys()].sort().join('&');
  return path + (query ? `?${query}` : '');
}
