/* ==========================================================================
   GENERAL QUERY CHATBOT (Groq-backed)
   Ask free-form questions; the backend grounds the answer in the latest
   detected anomaly's real evidence (see build_chat_response in api_server.py)
   rather than letting the model answer from unconstrained knowledge.
   ========================================================================== */

function toggleChatWidget() {
  const panel = document.getElementById('chatPanel');
  if (!panel) return;
  const opening = panel.style.display === 'none' || !panel.style.display;
  setChatWidgetOpen(opening);
}

function closeChatWidget() {
  setChatWidgetOpen(false);
}

function setChatWidgetOpen(open) {
  const panel = document.getElementById('chatPanel');
  const toggleBtn = document.getElementById('chatToggleBtn');
  if (panel) panel.style.display = open ? 'block' : 'none';
  // Hide the floating toggle pill while open -- #chatWidget is position:fixed
  // with only `bottom` set, so it grows *upward* as the panel's content
  // grows. With the toggle button also in the flow above the panel, it can
  // get pushed off the top of the viewport once the panel is tall, making it
  // unreachable to close. The panel's own close button (above) doesn't have
  // this problem since it's anchored inside the panel itself.
  if (toggleBtn) toggleBtn.style.display = open ? 'none' : 'inline-block';
}

function appendChatMessage(role, text) {
  const container = document.getElementById('chatMessages');
  if (!container) return null;
  const bubble = document.createElement('div');
  bubble.style.alignSelf = role === 'user' ? 'flex-end' : 'flex-start';
  bubble.style.background = role === 'user' ? '#10b981' : '#26262e';
  bubble.style.color = role === 'user' ? '#0a0a0a' : '#e5e7eb';
  bubble.style.padding = '6px 10px';
  bubble.style.borderRadius = '10px';
  bubble.style.maxWidth = '85%';
  bubble.style.whiteSpace = 'pre-wrap';
  bubble.style.fontSize = '12px';
  bubble.style.lineHeight = '1.4';
  bubble.textContent = text;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  if (!input || !input.value.trim()) return;
  const message = input.value.trim();
  input.value = '';
  appendChatMessage('user', message);
  const placeholder = appendChatMessage('assistant', 'Thinking...');

  try {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal: AbortSignal.timeout(20000)
    });
    const data = await res.json();
    if (placeholder) placeholder.remove();

    if (data.error) {
      appendChatMessage('assistant', `Error: ${data.error}`);
    } else {
      appendChatMessage('assistant', data.reply);
    }
  } catch (err) {
    if (placeholder) placeholder.remove();
    appendChatMessage('assistant', 'Failed to reach backend -- is the server running?');
  }
}
