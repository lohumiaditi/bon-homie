// Small fetch wrapper for the /facebook endpoints (JWT cookie is sent automatically).
export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch { /* empty body */ }
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`)
  return data
}

export function timeAgo(iso) {
  if (!iso) return 'never'
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function whatsappUrl(contact, lead) {
  const msg = `Hi! I saw your rental post${lead.area_name ? ` for ${lead.area_name}` : ''}` +
    `${lead.price ? ` at ₹${lead.price.toLocaleString('en-IN')}/month` : ''}. Is it still available?`
  return `https://wa.me/${contact.replace(/\D/g, '')}?text=${encodeURIComponent(msg)}`
}

export const card = 'bg-white rounded-2xl shadow-sm border border-gray-100 p-5'
export const btn = 'text-sm font-semibold px-4 py-2 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed'
export const btnPrimary = `${btn} bg-blue-600 text-white hover:bg-blue-700`
export const btnGhost = `${btn} border border-gray-200 text-gray-700 hover:bg-gray-50`
