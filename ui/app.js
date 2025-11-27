const chatEl = document.getElementById('chat');
const msgInput = document.getElementById('msg');
const sendBtn = document.getElementById('send');
const projectForm = document.getElementById('project-form');
const projectStatus = document.getElementById('project-status');

function appendMessage(role, text) {
  const entry = document.createElement('div');
  entry.className = 'chat-entry ' + role;
  entry.innerText = `${role}: ${text}`;
  chatEl.appendChild(entry);
  chatEl.scrollTop = chatEl.scrollHeight;
}

sendBtn.addEventListener('click', async () => {
  const message = msgInput.value.trim();
  if (!message) return;
  appendMessage('user', message);
  msgInput.value = '';
  sendBtn.disabled = true;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });

    if (!res.ok) {
      const text = await res.text();
      appendMessage('assistant', `Error: Server responded with ${res.status} - ${text}`);
      return;
    }

    const resp = await res.json();
    if (resp && resp.success) {
      if (resp.llm_mode) appendMessage('system', `LLM mode: ${resp.llm_mode}`);
      appendMessage('assistant', resp.answer);
    } else {
      appendMessage('assistant', 'Error: ' + (resp.error || 'Unknown'));
    }
  } catch (err) {
    appendMessage('assistant', 'Network error: ' + err.message);
  } finally {
    sendBtn.disabled = false;
  }
});

projectForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = new FormData(projectForm);
  const payload = {
    project_name: data.get('project_name'),
    module: data.get('module')
  };

  const resp = await fetch('/api/projects/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).then(r => r.json());

  if (resp && resp.success) {
    projectStatus.innerText = `Project created: ${resp.project_name} (session: ${resp.session_id})`;
    appendMessage('system', `Project ${resp.project_name} created with session ${resp.session_id}`);
  } else {
    projectStatus.innerText = 'Failed to create project';
  }
});
