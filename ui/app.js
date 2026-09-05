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
   Auth (JWT bearer token, kept only in this tab)
----------------------------- */

const TOKEN_STORAGE_KEY = 'erp_agent_access_token';

function getStoredToken() {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

function storeToken(token) {
  sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function loginOrSignup(email, password) {
  // Try login first; if the account doesn't exist yet, sign up instead.
  // This is a deliberately minimal shim - the real account UI comes with
  // the Stage 4/5 frontend rebuild.
  let response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });

  if (response.status === 401) {
    response = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
  }

  if (!response.ok) {
    return null;
  }

  const data = await response.json();
  return data.access_token || null;
}

async function promptForToken() {
  const email = window.prompt('Email:');
  if (!email) return null;

  const password = window.prompt('Password (8+ characters; first time here signs you up):');
  if (!password) return null;

  const token = await loginOrSignup(email, password);
  if (token) {
    storeToken(token);
  }
  return token;
}

async function getToken() {
  return getStoredToken() || await promptForToken();
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

  const token = await getToken();

  if (!token) {
    appendMessage('assistant', '**Error:** Login is required to use this assistant.');
    setLoading(false);
    return;
  }

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        message: message,
        session_id: currentSessionId
      })
    });

    if (response.status === 401) {
      clearToken();
      appendMessage(
        'assistant',
        '**Error:** Your session expired or the password was incorrect. Please try sending your message again to log back in.'
      );
      return;
    }

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