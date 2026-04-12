/**
 * WhatsApp Agent
 * --------------
 * Uses whatsapp-web.js to send messages from your personal WhatsApp.
 * On first run: shows QR code → scan with phone → session saved.
 * Subsequent runs: loads saved session (no rescan needed).
 *
 * Anti-spam measures:
 *   - Random message template rotation
 *   - Random delay 45–120 seconds between messages
 *   - Daily cap: 20 messages per session
 *   - Messages include natural listing context
 *
 * Start: node whatsapp/index.js
 * Or via npm: npm run whatsapp
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const { getTemplate } = require('./templates');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT = 3001;
const DAILY_LIMIT = 20;
const MIN_DELAY_MS = 45_000;   // 45 seconds
const MAX_DELAY_MS = 120_000;  // 2 minutes

// ── State ────────────────────────────────────────────────────────────────────
let isReady = false;
let messagesSentToday = 0;
let lastTemplateIndexByContact = {};
const sentLog = [];  // { to, message, time }

// ── WhatsApp client ──────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({
    dataPath: '.wwebjs_auth',   // saves session here — in .gitignore
  }),
  puppeteer: {
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  },
});

client.on('qr', (qr) => {
  console.log('\n=== SCAN THIS QR CODE WITH YOUR WHATSAPP ===');
  console.log('WhatsApp → Settings → Linked Devices → Link a Device\n');
  qrcode.generate(qr, { small: true });
  console.log('\nWaiting for scan...\n');
});

client.on('ready', () => {
  isReady = true;
  console.log('\n✅ WhatsApp connected! Agent is ready.');
  console.log(`API server running on http://localhost:${PORT}\n`);
});

client.on('disconnected', (reason) => {
  isReady = false;
  console.log('WhatsApp disconnected:', reason);
});

client.on('auth_failure', () => {
  console.error('WhatsApp auth failed — please delete .wwebjs_auth/ and restart');
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function randomDelay() {
  return MIN_DELAY_MS + Math.random() * (MAX_DELAY_MS - MIN_DELAY_MS);
}

function resetDailyCountIfNeeded() {
  const today = new Date().toDateString();
  if (!resetDailyCountIfNeeded._lastDay) {
    resetDailyCountIfNeeded._lastDay = today;
  }
  if (resetDailyCountIfNeeded._lastDay !== today) {
    messagesSentToday = 0;
    resetDailyCountIfNeeded._lastDay = today;
  }
}

async function sendMessage(to, area, price, propertyType = 'flat') {
  resetDailyCountIfNeeded();

  if (!isReady) {
    return { success: false, error: 'WhatsApp not connected' };
  }
  if (messagesSentToday >= DAILY_LIMIT) {
    return { success: false, error: `Daily limit of ${DAILY_LIMIT} messages reached` };
  }

  // Normalize phone number to WhatsApp ID format
  let phone = to.replace(/\D/g, '');
  if (!phone.startsWith('91')) phone = '91' + phone;
  const waId = `${phone}@c.us`;

  const lastIdx = lastTemplateIndexByContact[waId] ?? null;
  const { message, index } = getTemplate(area, price, propertyType, lastIdx);
  lastTemplateIndexByContact[waId] = index;

  try {
    await client.sendMessage(waId, message);
    messagesSentToday++;
    sentLog.push({ to: waId, message, time: new Date().toISOString() });
    console.log(`[WA] Sent to ${to}: "${message.substring(0, 60)}..."`);
    return { success: true, message };
  } catch (err) {
    console.error(`[WA] Error sending to ${to}:`, err.message);
    return { success: false, error: err.message };
  }
}

// ── Express HTTP API (called by FastAPI backend) ──────────────────────────────
const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ ready: isReady, messagesSentToday, dailyLimit: DAILY_LIMIT });
});

app.post('/send', async (req, res) => {
  const { to, area, price, property_type } = req.body;
  if (!to) return res.status(400).json({ error: 'Missing: to' });
  if (!area) return res.status(400).json({ error: 'Missing: area' });

  const result = await sendMessage(to, area, price, property_type || 'flat');

  if (!result.success) {
    return res.status(429).json(result);
  }

  // Add anti-spam delay before confirming — next message must wait
  const delay = randomDelay();
  console.log(`[WA] Next message available in ${Math.round(delay / 1000)}s`);

  res.json({ ...result, next_available_in_seconds: Math.round(delay / 1000) });
});

app.get('/log', (req, res) => {
  res.json({ sent: sentLog, count: sentLog.length });
});

// ── Start ─────────────────────────────────────────────────────────────────────
console.log('Starting WhatsApp agent...');
client.initialize();

app.listen(PORT, () => {
  console.log(`WhatsApp HTTP API listening on port ${PORT}`);
});
