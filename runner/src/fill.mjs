// Synthetic, clearly fake values for form fields. Nothing here resembles real personal data.

const today = () => new Date().toISOString().slice(0, 10);

export function suffix(seed) {
  let h = 2166136261;
  for (const ch of String(seed)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  return h.toString(36).slice(0, 4);
}

/** Value for one field, or null when the field should be left as the page rendered it. */
export function valueFor(field, seed = '') {
  const name = field.name.toLowerCase();
  const tag = suffix(seed + name);
  if (field.kind === 'select') return field.options?.[0] ?? null;
  if (field.kind === 'checkbox' || field.kind === 'radio') return 'check';
  if (field.type === 'email' || name.includes('email')) return `archintel-${tag}@example.test`;
  if (field.type === 'tel' || /phone|telephone|mobile/.test(name)) return '6085550' + String(parseInt(tag, 36) % 1000).padStart(3, '0');
  if (field.type === 'date' || /date|birth/.test(name)) return name.includes('birth') ? '2019-05-17' : today();
  if (field.type === 'number' || /(^|[^a-z])(age|count|quantity|amount)/.test(name)) return '3';
  if (field.type === 'password') return null;                          // never invent credentials
  if (/zip|postal/.test(name)) return '53703';
  if (/city/.test(name)) return 'Testville';
  if (/address|street/.test(name)) return `${parseInt(tag, 36) % 900 + 100} Sample Street`;
  if (/first/.test(name)) return 'Alex';
  if (/last|surname/.test(name)) return `Tester${tag}`;
  if (/description|comment|note|text/.test(name) || field.type === 'textarea') return `Recorded by ArchIntel exploration ${tag}`;
  if (/name/.test(name)) return `Sample ${tag}`;
  if (/search|query|^q$/.test(name)) return '';
  return `test-${tag}`;
}

/** REA actions that fill a form and submit it. Returns null when the form cannot be submitted safely. */
export function formActions(form, seed, stepPrefix) {
  if (!form.submit) return null;
  if (form.fields.some((f) => f.type === 'password')) return null;      // login and account forms are out of scope
  const actions = [];
  let n = 0;
  for (const field of form.fields) {
    const value = valueFor(field, seed);
    if (value === null) continue;
    const step_id = `${stepPrefix}-f${n++}`;
    const locator = { kind: 'css', selector: field.selector };
    if (field.kind === 'select') actions.push({ step_id, action: 'select_option', locator, value: { source: 'literal', value }, timeout_ms: 10000 });
    else if (field.kind === 'checkbox' || field.kind === 'radio') actions.push({ step_id, action: 'check', locator, timeout_ms: 10000 });
    else actions.push({ step_id, action: 'fill', locator, value: { source: 'literal', value }, timeout_ms: 10000 });
  }
  actions.push({ step_id: `${stepPrefix}-submit`, action: 'click', locator: { kind: 'css', selector: form.submit }, timeout_ms: 15000 });
  actions.push({ step_id: `${stepPrefix}-settle`, action: 'wait_for_timeout', duration_ms: 600 });
  return actions;
}
