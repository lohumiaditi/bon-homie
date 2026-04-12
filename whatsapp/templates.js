/**
 * WhatsApp Message Templates
 * --------------------------
 * 10+ variants to avoid spam detection.
 * Randomly rotated — never same template twice in a row per contact.
 */

const templates = [
  (area, price, type) =>
    `Hi! I saw your ${type} listing in ${area}${price ? ` (₹${price}/month)` : ''}. Is it still available for rent?`,

  (area, price, type) =>
    `Hello, I came across your ${type} in ${area}. Could you please share more details? My budget is around ₹${price || 'XX,XXX'}/month.`,

  (area, price, type) =>
    `Good day! I'm looking for a ${type} in ${area} within ₹${price || 'XX,XXX'}/month. Is your listing still open?`,

  (area, price, type) =>
    `Hi there! I'm interested in the ${type} you listed in ${area}. Would love to schedule a visit if it's available.`,

  (area, price, type) =>
    `Hello! Found your rental listing in ${area}${price ? ` at ₹${price}` : ''}. Is it still on the market?`,

  (area, price, type) =>
    `Hi! I've been searching for a ${type} in ${area}. Your listing caught my attention — is it available?`,

  (area, price, type) =>
    `Good morning! I'm actively looking for a place in ${area}. Your ${type} at ₹${price || 'the listed price'} looks interesting. Still available?`,

  (area, price, type) =>
    `Hello! Saw your ${type} in ${area}. I'd like to know if it's available and when I could schedule a viewing.`,

  (area, price, type) =>
    `Hi! I'm looking for a ${type} in ${area} for immediate occupancy. Budget: ₹${price || 'XX,XXX'}/month. Is it still available?`,

  (area, price, type) =>
    `Hello! I noticed your ${type} listing in ${area}. Could you share details about the property? I'm looking to move in soon.`,

  (area, price, type) =>
    `Hi! Your listing in ${area} looks great. I'm a working professional looking for a clean ${type}. Is it available?`,
];

/**
 * Get a random template that differs from the last used one.
 * @param {number|null} lastTemplateIndex - Index of last template used (to avoid repeat)
 * @returns {{ message: string, index: number }}
 */
function getTemplate(area, price, type = 'flat', lastTemplateIndex = null) {
  let idx;
  do {
    idx = Math.floor(Math.random() * templates.length);
  } while (idx === lastTemplateIndex && templates.length > 1);

  return {
    message: templates[idx](area, price, type),
    index: idx,
  };
}

module.exports = { getTemplate, templates };
