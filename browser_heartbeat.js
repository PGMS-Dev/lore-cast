/**
 * Lore-Cast Browser Heartbeat
 * Injected via javascript_tool when operating in Browser mode.
 *
 * Sets up a recurring state check in the browser and stores results
 * in window._lc_state for Claude to read between actions.
 *
 * Usage (inject once after session creation):
 *   Replace {SHORT_ID} and {INTERVAL_MS} before injecting.
 *   Default interval: 90000ms (90 seconds)
 */

(function startLoreCastHeartbeat(shortId, token, intervalMs) {

  // Stop any existing heartbeat before starting a new one
  if (window._lc_heartbeatId) {
    clearInterval(window._lc_heartbeatId);
    console.log('[LoreCast] Previous heartbeat cleared.');
  }

  // sessionToken passed as query param for GM-extended view (includes unreadMessages)
  const stateUrl = `/api/table/sessions/${shortId}/state?sessionToken=${token}`;

  async function ping() {
    try {
      const resp = await fetch(stateUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const state = await resp.json();

      state._checkedAt = new Date().toISOString();
      state._source    = 'browser-heartbeat';
      window._lc_state = state;

      // If there are unread messages, fetch pending chat queue
      if (state.unreadMessages > 0) {
        try {
          const pendingResp = await fetch(`/api/table/chat/pending?sessionToken=${token}`);
          const pending     = await pendingResp.json();
          // pending: [{ playerId, playerName, messageCount, lastMessage, lastMessageAt }]
          window._lc_pendingMessages = pending;
          const total = pending.reduce((sum, p) => sum + (p.messageCount || 1), 0);
          console.warn(`[LoreCast] 📨 ${total} unread message(s) from ${pending.length} player(s) — window._lc_pendingMessages`);
        } catch (e) {
          console.warn('[LoreCast] Could not fetch pending chat:', e);
        }
      }

      // Warn in console if something needs attention
      if (!state.isActive) {
        console.error('[LoreCast] 💀 Session is no longer active! window._lc_state.isActive = false');
      } else if (state.viewerCount === 0) {
        console.warn('[LoreCast] ⚠ No viewers connected. window._lc_state.viewerCount = 0');
      } else {
        console.log(`[LoreCast] 💓 active=true | viewers=${state.viewerCount} | unread=${state.unreadMessages}`);
      }

    } catch (err) {
      window._lc_state = {
        isActive: false,
        viewerCount: 0,
        unreadMessages: 0,
        error: err.message,
        _checkedAt: new Date().toISOString(),
        _source: 'browser-heartbeat-error'
      };
      console.error('[LoreCast] ❌ Heartbeat ping failed:', err.message);
    }
  }

  // Run immediately, then on interval
  ping();
  window._lc_heartbeatId = setInterval(ping, intervalMs);

  console.log(`[LoreCast] 💓 Browser heartbeat started — session ${shortId}, interval ${intervalMs / 1000}s`);
  console.log('[LoreCast] Read state anytime with: window._lc_state');
  console.log('[LoreCast] Pending player messages: window._lc_pendingMessages');
  console.log('[LoreCast] Stop with: clearInterval(window._lc_heartbeatId)');

// Also expose a convenience reply function for Claude to use
window._lc_reply = (playerId, message) =>
  fetch('/api/table/chat/reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionToken: token, playerId, message })
  }).then(r => r.json()).then(d => { window._lc_lastReply = d; return d; });

console.log('[LoreCast] Reply to player: window._lc_reply(playerId, "message")');

})("{SHORT_ID}", "{SESSION_TOKEN}", 90000);
