const chatEl = document.getElementById('chat');
const msgInput = document.getElementById('msg');
const sendBtn = document.getElementById('send');
const sessionBanner = document.getElementById('session-banner');

let currentSessionId = null;


/* -----------------------------
   Markdown
----------------------------- */

function renderMarkdown(text) {
  if (!window.marked) {
    return escapeHtml(text);
  }

  return window.marked.parse(text, {
    gfm: true,
    breaks: true
  });
}


/* -----------------------------
   Security
----------------------------- */

function escapeHtml(text) {
  const div = document.createElement('div');
  div.innerText = text;
  return div.innerHTML;
}


/* -----------------------------
   Messages
----------------------------- */

function appendMessage(role, text) {
  const entry = document.createElement('div');

  entry.className = `chat-entry ${role}`;

  if (role === 'assistant') {
    entry.innerHTML = renderMarkdown(text);
  } else {
    entry.innerText = text;
  }

  chatEl.appendChild(entry);

  scrollToBottom();
}


function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}


/* -----------------------------
   Existing conversation
----------------------------- */

function renderExistingMessages() {
  const messages = chatEl.querySelectorAll('.chat-entry');

  messages.forEach((entry) => {
    const role = entry.dataset.role;
    const text = entry.dataset.content || '';

    if (role === 'assistant') {
      entry.innerHTML = renderMarkdown(text);
    } else {
      entry.innerText = text;
    }
  });

  scrollToBottom();
}


/* -----------------------------
   Session
----------------------------- */

function updateSessionBanner() {
  if (currentSessionId) {
    sessionBanner.innerText =
      `Active project session: ${currentSessionId}`;
  } else {
    sessionBanner.innerText =
      "No active project - just tell me what you'd like to start.";
  }
}


function setSessionId(sessionId) {
  if (!sessionId || sessionId === currentSessionId) {
    return;
  }

  currentSessionId = sessionId;
  updateSessionBanner();
}


/* -----------------------------
   Loading state
----------------------------- */

function setLoading(isLoading) {
  sendBtn.disabled = isLoading;
  msgInput.disabled = isLoading;

  sendBtn.innerText = isLoading ? 'Sending...' : 'Send';
}


/* -----------------------------
   API
----------------------------- */

async function sendMessage() {
  const message = msgInput.value.trim();

  if (!message || sendBtn.disabled) {
    return;
  }

  appendMessage('user', message);

  msgInput.value = '';
  setLoading(true);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': window.API_KEY
      },
      body: JSON.stringify({
        message: message,
        session_id: currentSessionId
      })
    });

    if (!response.ok) {
      const errorText = await response.text();

      appendMessage(
        'assistant',
        `**Error:** Server responded with ${response.status}\n\n${errorText}`
      );

      return;
    }

    const data = await response.json();

    if (!data || !data.success) {
      const errorMessage =
        data?.answer ||
        data?.error ||
        'Unknown server error.';

      appendMessage(
        'assistant',
        `**Error:** ${errorMessage}`
      );

      return;
    }

    setSessionId(data.session_id);

    appendMessage(
      'assistant',
      data.answer || 'No response received.'
    );

  } catch (error) {
    appendMessage(
      'assistant',
      `**Network error:** ${error.message}`
    );

  } finally {
    setLoading(false);
    msgInput.focus();
  }
}


/* -----------------------------
   Event listeners
----------------------------- */

sendBtn.addEventListener('click', sendMessage);

msgInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});


/* -----------------------------
   Initialisation
----------------------------- */

function initialiseChat() {
  renderExistingMessages();
  updateSessionBanner();
  msgInput.focus();
}

initialiseChat();