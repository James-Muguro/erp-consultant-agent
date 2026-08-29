const chatEl = document.getElementById('chat');
const msgInput = document.getElementById('msg');
const sendBtn = document.getElementById('send');
const sessionBanner = document.getElementById('session-banner');

let currentSessionId = null;

function appendMessage(role, text) {
  const entry = document.createElement('div');
  entry.className = 'chat-entry ' + role;
  entry.innerText = `${role}: ${text}`;
  chatEl.appendChild(entry);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function updateSessionBanner() {
  sessionBanner.innerText = currentSessionId
    ? `Active project session: ${currentSessionId}`
    : "No active project - just tell me what you'd like to start.";
}

async function sendMessage() {
  const message = msgInput.value.trim();
  if (!message) return;
  appendMessage('user', message);
  msgInput.value = '';
  sendBtn.disabled = true;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': window.API_KEY },
      body: JSON.stringify({ message, session_id: currentSessionId })
    });

    if (!res.ok) {
      const text = await res.text();
      appendMessage('assistant', `Error: Server responded with ${res.status} - ${text}`);
      return;
    }

    const resp = await res.json();
    if (resp && resp.success) {
      if (resp.session_id && resp.session_id !== currentSessionId) {
        currentSessionId = resp.session_id;
        updateSessionBanner();
      }
      appendMessage('assistant', resp.answer);
    } else {
      appendMessage('assistant', 'Error: ' + (resp.answer || resp.error || 'Unknown'));
    }
  } catch (err) {
    appendMessage('assistant', 'Network error: ' + err.message);
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener('click', sendMessage);
msgInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});