// Inicializar al cargar la página
window.addEventListener('DOMContentLoaded', () => {
  // Inicializar campo API
  const apiInput = document.getElementById('api-server-url');
  if (apiInput) {
    apiInput.value = localStorage.getItem('api_server_url') || '';
  }
  
  // Cargar tema guardado
  const currentTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', currentTheme);
  updateThemeIcon(currentTheme);

  // Cargar lista de archivos temporales
  loadFiles();

  // Inicializar voces del reproductor TTS
  initTTSVoices();

  // Actualizar estado e icono del conmutador de sonido
  updateSoundIcon();
});

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
  updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
  const themeIcon = document.getElementById('theme-icon');
  if (themeIcon) {
    themeIcon.textContent = theme === 'dark' ? '☀️' : '🌙';
  }
}

function saveApiUrl(val) {
  if (val.trim()) {
    // Asegurar que comience con http:// o https://
    if (!/^https?:\/\//i.test(val)) {
      val = 'http://' + val;
    }
    localStorage.setItem('api_server_url', val.trim());
    showNotification('Dirección del servidor API guardada: ' + val.trim());
    setTimeout(hideNotification, 2000);
  } else {
    localStorage.removeItem('api_server_url');
    showNotification('Usando dirección del servidor por defecto.');
    setTimeout(hideNotification, 2000);
  }
}

function getApiUrl(endpoint) {
  const savedUrl = localStorage.getItem('api_server_url') || '';
  if (savedUrl) {
    const base = savedUrl.endsWith('/') ? savedUrl.slice(0, -1) : savedUrl;
    return base + endpoint;
  }
  return endpoint;
}

// Gestión de Archivos Temporales
function loadFiles() {
  fetch(getApiUrl('/api/files'))
  .then(res => res.json())
  .then(data => {
    renderFileList('yt-file-list', data.yt_files, 'yt');
    renderFileList('video-file-list', data.video_files, 'video');
    renderFileList('uploaded-file-list', data.uploaded_files, 'upload');
    renderFileList('mp3-file-list', data.mp3_files, 'mp3');
    renderFileList('trimmed-file-list', data.trimmed_files, 'trimmed');
    renderFileList('merged-file-list', data.merged_files, 'merged');
  })
  .catch(err => {
    console.error('Error cargando lista de archivos:', err);
  });
}

function renderFileList(containerId, files, category) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.replaceChildren();
  if (!files || files.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'No hay archivos en esta carpeta.';
    container.appendChild(empty);
    return;
  }
  const endpoints = { merged: '/api/merge/file/', trimmed: '/api/trim/file/',
    video: '/api/download_video/file/', mp3: '/api/download/mp3/' };
  for (const file of files) {
    const row = document.createElement('div');
    row.className = 'file-row';
    const details = document.createElement('div');
    details.className = 'file-details';
    const name = document.createElement('span');
    name.textContent = file.name;
    name.title = file.name;
    const size = document.createElement('small');
    size.textContent = file.size;
    details.append(name, size);
    const actions = document.createElement('div');
    actions.className = 'file-actions';
    if (endpoints[category]) {
      const link = document.createElement('a');
      link.className = 'btn btn--ghost';
      link.textContent = '📥';
      link.title = 'Descargar archivo';
      link.href = getApiUrl(endpoints[category] + encodeURIComponent(file.name));
      link.download = file.name;
      actions.appendChild(link);
    }
    const transcribe = document.createElement('button');
    transcribe.className = 'btn btn--ghost';
    transcribe.textContent = '🎙️';
    transcribe.title = 'Cargar en transcriptor';
    transcribe.addEventListener('click', () => loadIntoTranscriptor(file.path));
    const remove = document.createElement('button');
    remove.className = 'btn btn--ghost';
    remove.textContent = '🗑️';
    remove.title = 'Eliminar archivo';
    remove.addEventListener('click', () => deleteFile(category, file.name));
    actions.append(transcribe, remove);
    row.append(details, actions);
    container.appendChild(row);
  }
}

function deleteFile(category, filename) {
  if (!confirm(`¿Estás seguro de que deseas eliminar el archivo "${filename}"?`)) return;
  
  fetch(getApiUrl('/api/files'), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, filename })
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showNotification('Error al eliminar archivo: ' + data.error, 'error');
    } else {
      showNotification(data.message || 'Archivo eliminado correctamente.');
      setTimeout(hideNotification, 2000);
      loadFiles();
    }
  })
  .catch(err => {
    showNotification('Error de red al eliminar: ' + err.message, 'error');
  });
}

function clearCategory(category) {
  let catName = 'los archivos';
  if (category === 'yt') catName = 'los audios de YouTube';
  else if (category === 'video') catName = 'los videos de YouTube MP4';
  else if (category === 'upload') catName = 'los archivos locales subidos';
  else if (category === 'mp3') catName = 'los MP3 convertidos';
  else if (category === 'trimmed') catName = 'los recortes multimedia';
  else if (category === 'merged') catName = 'los archivos fusionados';
  
  if (!confirm(`¿Estás seguro de que deseas eliminar TODOS ${catName}?`)) return;
  
  fetch(getApiUrl('/api/files'), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category })
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showNotification('Error al vaciar carpeta: ' + data.error, 'error');
    } else {
      showNotification(data.message || 'Carpeta vaciada correctamente.');
      setTimeout(hideNotification, 2000);
      loadFiles();
    }
  })
  .catch(err => {
    showNotification('Error de red al vaciar carpeta: ' + err.message, 'error');
  });
}

let currentTab = 'tab-link';
let statusInterval = null;
let lastTranscription = '';
let lastSource = '';
let lastModel = '';
let lastLanguage = '';

function switchTab(tabId) {
  currentTab = tabId;
  const transcriptorTabs = document.querySelector('#view-transcriptor .tab-container');
  transcriptorTabs.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('is-active');
  });
  document.getElementById('tab-link').classList.remove('is-active');
  document.getElementById('tab-local').classList.remove('is-active');
  
  // Find triggering button
  const btnIndex = tabId === 'tab-link' ? 0 : 1;
  transcriptorTabs.querySelectorAll('.tab-button')[btnIndex].classList.add('is-active');
  document.getElementById(tabId).classList.add('is-active');
}

function showNotification(message, type = 'success') {
  const notif = document.getElementById('status-notification');
  notif.textContent = message;
  notif.className = 'notification ' + (type === 'success' ? 'notification--success' : 'notification--error');
  notif.style.display = 'block';
}

function hideNotification() {
  document.getElementById('status-notification').style.display = 'none';
}

function copyToClipboard() {
  const text = document.getElementById('transcription-text').textContent;
  navigator.clipboard.writeText(text).then(() => {
    showNotification('Transcripción copiada al portapapeles.');
    setTimeout(hideNotification, 3000);
  });
}

// ==========================================
// SISTEMA DE COLA DE TAREAS Y PROCESAMIENTO POR LOTES
// ==========================================
let isAudioBatchMode = false;
let isVideoBatchMode = false;
let taskQueue = []; // Array de { id, type: 'transcribe'|'video_download', title, payload, fileObj, status, message }
let isQueueProcessing = false;
let currentQueueTask = null;

function toggleAudioBatchMode() {
  isAudioBatchMode = !isAudioBatchMode;
  document.getElementById('single-audio-url-wrapper').style.display = isAudioBatchMode ? 'none' : 'block';
  document.getElementById('batch-audio-url-wrapper').style.display = isAudioBatchMode ? 'block' : 'none';
  document.getElementById('btn-audio-batch-label').textContent = isAudioBatchMode ? '🔗 Enlace Único' : '📋 Múltiples Enlaces (Por Lotes)';
}

function toggleVideoBatchMode() {
  isVideoBatchMode = !isVideoBatchMode;
  document.getElementById('single-video-url-wrapper').style.display = isVideoBatchMode ? 'none' : 'block';
  document.getElementById('batch-video-url-wrapper').style.display = isVideoBatchMode ? 'block' : 'none';
  document.getElementById('btn-video-batch-label').textContent = isVideoBatchMode ? '🔗 Enlace Único' : '📋 Múltiples Enlaces (Por Lotes)';
}

function addTasksToQueue(tasks) {
  if (!Array.isArray(tasks)) tasks = [tasks];
  for (let t of tasks) {
    taskQueue.push({
      id: 'task_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
      type: t.type,
      title: t.title || (t.type === 'video_download' ? 'Descarga de Video' : 'Transcripción'),
      payload: t.payload,
      fileObj: t.fileObj || null,
      status: 'waiting',
      message: 'En espera en la cola...'
    });
  }
  renderQueuePanel();
  showNotification(`Se añadieron ${tasks.length} tarea(s) a la cola de procesamiento.`, 'success');
  if (!isQueueProcessing) {
    processNextQueueTask();
  }
}

function escapeHtml(value) {
  const element = document.createElement('span');
  element.textContent = String(value ?? '');
  return element.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showTranscriptionDownloads(data) {
  const panel = document.getElementById('transcription-downloads');
  panel.replaceChildren();
  for (const [extension, filename] of Object.entries(data.output_files || {})) {
    const link = document.createElement('a');
    link.className = 'btn btn--ghost';
    link.textContent = extension.toUpperCase();
    link.href = getApiUrl('/api/transcriptions/' + encodeURIComponent(filename));
    link.download = filename;
    panel.appendChild(link);
  }
  document.getElementById('transcription-performance').textContent =
    `${(data.device || '').toUpperCase()} · ${data.inference_seconds || 0} s de transcripción · ${Math.round(data.audio_seconds || 0)} s de audio. ${data.warning || ''}`;
}

function renderQueuePanel() {
  const panel = document.getElementById('global-queue-panel');
  const badge = document.getElementById('queue-badge-count');
  const container = document.getElementById('queue-items-container');
  if (!panel || !container) return;

  if (taskQueue.length === 0) {
    panel.style.display = 'none';
    return;
  }

  panel.style.display = 'block';
  const waitingCount = taskQueue.filter(t => t.status === 'waiting' || t.status === 'processing').length;
  badge.textContent = `${waitingCount} en cola`;

  container.innerHTML = taskQueue.map((t, idx) => {
    let statusBadge = '';
    if (t.status === 'waiting') {
      statusBadge = `<span style="background: rgba(255, 193, 7, 0.2); color: #d97706; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 600;">⏳ En espera</span>`;
    } else if (t.status === 'processing') {
      statusBadge = `<span style="background: rgba(13, 110, 253, 0.2); color: #0d6efd; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 600;">🔄 Procesando...</span>`;
    } else if (t.status === 'completed') {
      statusBadge = `<span style="background: rgba(25, 135, 84, 0.2); color: #198754; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 600;">✅ Completado</span>`;
    } else if (t.status === 'error') {
      statusBadge = `<span style="background: rgba(220, 53, 69, 0.2); color: #dc3545; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.78rem; font-weight: 600;">❌ Error</span>`;
    }

    return `
      <div style="display: flex; justify-content: space-between; align-items: center; background: var(--panel); padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid var(--border); font-size: 0.88rem;">
        <div style="display: flex; align-items: center; gap: 0.6rem; min-width: 0; flex-grow: 1; padding-right: 0.5rem;">
          <span style="font-weight: 600; color: var(--accent); flex-shrink: 0;">#${idx + 1}</span>
          <div style="display: flex; flex-direction: column; min-width: 0;">
            <span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--accent-strong);" title="${escapeHtml(t.title)}">${escapeHtml(t.title)}</span>
            <span style="font-size: 0.78rem; color: var(--muted);">${escapeHtml(t.message)}</span>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0;">
          ${statusBadge}
          ${t.status === 'waiting' ? `<button class="btn btn--ghost" style="padding: 0.2rem 0.4rem; font-size: 0.8rem; color: #d9534f;" onclick="removeTaskFromQueue('${t.id}')" title="Quitar de la cola">❌</button>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function removeTaskFromQueue(taskId) {
  taskQueue = taskQueue.filter(t => t.id !== taskId);
  renderQueuePanel();
}

function clearBatchQueue() {
  if (!confirm('¿Deseas vaciar todas las tareas en espera de la cola?')) return;
  taskQueue = taskQueue.filter(t => t.status === 'processing');
  renderQueuePanel();
}

async function cancelCurrentQueueTask() {
  if (!currentQueueTask) return;
  const endpoint = currentQueueTask.type === 'transcribe'
    ? '/api/transcribe/cancel' : '/api/download_video/cancel';
  try {
    const response = await fetch(getApiUrl(endpoint), { method: 'POST' });
    if (!response.ok) throw new Error('No se pudo solicitar la cancelación.');
    showNotification('Deteniendo la tarea. La cola continuar? al liberar sus recursos.');
  } catch (error) {
    showNotification(error.message, 'error');
  }
}

async function processNextQueueTask() {
  if (isQueueProcessing) return;
  const nextTask = taskQueue.find(t => t.status === 'waiting');
  if (!nextTask) {
    isQueueProcessing = false;
    currentQueueTask = null;
    renderQueuePanel();
    return;
  }

  isQueueProcessing = true;
  currentQueueTask = nextTask;
  currentQueueTask.status = 'processing';
  currentQueueTask.message = 'Iniciando ejecución...';
  renderQueuePanel();

  try {
    if (currentQueueTask.type === 'transcribe') {
      await executeTranscribeTask(currentQueueTask);
    } else if (currentQueueTask.type === 'video_download') {
      await executeVideoDownloadTask(currentQueueTask);
    }
  } catch (err) {
    nextTask.status = 'error';
    nextTask.message = err.message || 'Error en ejecución';
    renderQueuePanel();
  }

  isQueueProcessing = false;
  document.getElementById('btn-transcribe').disabled = false;
  setTimeout(processNextQueueTask, 1000);
}

async function executeTranscribeTask(task) {
  showView('transcriptor');
  document.getElementById('placeholder-wrapper').style.display = 'none';
  document.getElementById('result-wrapper').style.display = 'none';
  document.getElementById('progress-wrapper').style.display = 'block';
  document.getElementById('btn-transcribe').disabled = true;

  let res, data;
  if (task.fileObj) {
    const formData = new FormData();
    formData.append('file', task.fileObj);
    formData.append('model', task.payload.model);
    formData.append('language', task.payload.language);
    formData.append('device', task.payload.device);
    formData.append('quality', task.payload.quality);
    formData.append('initial_prompt', task.payload.initial_prompt);

    res = await fetch(getApiUrl('/api/transcribe'), {
      method: 'POST',
      body: formData
    });
  } else {
    res = await fetch(getApiUrl('/api/transcribe'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(task.payload)
    });
  }

  data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Error al iniciar la transcripción.');

  try {
    while (true) {
      await new Promise(resolve => setTimeout(resolve, 750));
      const response = await fetch(getApiUrl('/api/status'));
      if (!response.ok) throw new Error('No se pudo consultar el progreso.');
      const state = await response.json();
      document.getElementById('progress-bar-fill').style.width = `${state.percent}%`;
      document.getElementById('progress-percentage').textContent = `${state.percent}%`;
      document.getElementById('progress-status').textContent = state.message;
      task.message = state.message;
      renderQueuePanel();
      if (state.status === 'completed') {
        lastTranscription = state.transcription;
        lastSource = task.title;
        lastModel = state.model;
        lastLanguage = state.language;
        document.getElementById('transcription-text').textContent = state.transcription;
        document.getElementById('output-directory').textContent = state.output_dir;
        document.getElementById('result-wrapper').style.display = 'flex';
        analyzeTranscriptionStats(state.transcription);
        showTranscriptionDownloads(state);
        if (!state.transcription) showNotification(state.message);
        task.status = 'completed';
        task.message = state.message;
        renderQueuePanel();
        playCompletionChime();
        loadFiles();
        return;
      }
      if (state.status === 'error' || state.status === 'idle') {
        throw new Error(state.message);
      }
    }
  } finally {
    document.getElementById('progress-wrapper').style.display = 'none';
    document.getElementById('btn-transcribe').disabled = false;
  }
}

async function executeVideoDownloadTask(task) {
  showView('video-downloader');
  document.getElementById('video-placeholder-wrapper').style.display = 'none';
  document.getElementById('video-result-wrapper').style.display = 'none';
  document.getElementById('video-progress-wrapper').style.display = 'block';
  document.getElementById('btn-start-video-download').disabled = true;

  const res = await fetch(getApiUrl('/api/download_video'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task.payload)
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Error al iniciar la descarga.');

  await new Promise((resolve, reject) => {
    const pollInt = setInterval(async () => {
      try {
        const sRes = await fetch(getApiUrl('/api/download_video/status'));
        const sData = await sRes.json();
        document.getElementById('video-progress-bar-fill').style.width = `${sData.percent}%`;
        document.getElementById('video-progress-percentage').innerText = `${sData.percent}%`;
        document.getElementById('video-progress-status').innerHTML = `<span class="progress-spinner"></span>${escapeHtml(sData.message)}`;
        task.message = sData.message;
        renderQueuePanel();

        if (sData.status === 'completed') {
          clearInterval(pollInt);
          document.getElementById('video-progress-wrapper').style.display = 'none';
          document.getElementById('btn-start-video-download').disabled = false;

          document.getElementById('video-result-filename').innerText = sData.filename;
          document.getElementById('video-result-filesize').innerText = sData.filesize;
          document.getElementById('video-output-directory').innerText = sData.filepath;

          const dlBtn = document.getElementById('btn-download-video-file');
          dlBtn.href = getApiUrl(`/api/download_video/file/${encodeURIComponent(sData.filename)}`);
          dlBtn.download = sData.filename;

          document.getElementById('video-result-wrapper').style.display = 'flex';
          playCompletionChime();
          task.status = 'completed';
          task.message = 'Descargado exitosamente';
          renderQueuePanel();
          loadFiles();
          resolve();
        } else if (sData.status === 'error' || sData.status === 'idle') {
          clearInterval(pollInt);
          document.getElementById('video-progress-wrapper').style.display = 'none';
          document.getElementById('btn-start-video-download').disabled = false;
          document.getElementById('video-placeholder-wrapper').style.display = 'flex';
          playErrorChime();
          reject(new Error(sData.message));
        }
      } catch (e) {
        clearInterval(pollInt);
        reject(e);
      }
    }, 1000);
  });
}

function startTranscription() {
  hideNotification();
  const model = document.getElementById('whisper-model').value;
  const language = document.getElementById('audio-language').value;
  const device = document.getElementById('transcription-device').value;
  const quality = document.getElementById('transcription-quality').value;
  const initial_prompt = document.getElementById('transcription-glossary').value.trim();
  const tasks = [];

  if (currentTab === 'tab-link') {
    if (isAudioBatchMode) {
      const rawUrls = document.getElementById('audio-url-batch').value.split('\n');
      const urls = rawUrls.map(u => u.trim()).filter(u => u.length > 0);
      if (urls.length === 0) {
        showNotification('Por favor ingresa al menos una URL válida en la lista por lotes.', 'error');
        return;
      }
      for (let url of urls) {
        tasks.push({
          type: 'transcribe',
          source_type: 'url',
          title: 'YT Transcripción: ' + (url.length > 40 ? url.substring(0, 37) + '...' : url),
          payload: { source_type: 'url', url, model, language, device, quality, initial_prompt }
        });
      }
    } else {
      const url = document.getElementById('audio-url').value.trim();
      if (!url) {
        showNotification('Por favor ingresa una URL válida.', 'error');
        return;
      }
      tasks.push({
        type: 'transcribe',
        source_type: 'url',
        title: 'YT Transcripción: ' + (url.length > 40 ? url.substring(0, 37) + '...' : url),
        payload: { source_type: 'url', url, model, language, device, quality, initial_prompt }
      });
    }
  } else {
    const fileInput = document.getElementById('local-file-picker');
    const localPath = document.getElementById('audio-local-path').value.trim();

    if (fileInput.files && fileInput.files.length > 0) {
      for (let i = 0; i < fileInput.files.length; i++) {
        const f = fileInput.files[i];
        tasks.push({
          type: 'transcribe',
          source_type: 'upload',
          title: 'Archivo: ' + f.name,
          fileObj: f,
          payload: { source_type: 'upload', model, language, device, quality, initial_prompt }
        });
      }
    } else if (localPath) {
      tasks.push({
        type: 'transcribe',
        source_type: 'local_path',
        title: 'Ruta: ' + localPath.split('/').pop().split('\\').pop(),
        payload: { source_type: 'local_path', local_path: localPath, model, language, device, quality, initial_prompt }
      });
    } else {
      showNotification('Debe ingresar una ruta absoluta o seleccionar al menos un archivo.', 'error');
      return;
    }
  }

  addTasksToQueue(tasks);
}

function showError(msg) {
  showNotification(msg, 'error');
  document.getElementById('progress-wrapper').style.display = 'none';
  document.getElementById('placeholder-wrapper').style.display = 'flex';
  document.getElementById('btn-transcribe').disabled = false;
  if (statusInterval) clearInterval(statusInterval);
  loadFiles();
}

async function cancelTranscription() {
  await cancelCurrentQueueTask();
}

async function saveFileLocally(content, filename, mimeType, extension) {
  // Try the modern browser File System Access API
  if ('showSaveFilePicker' in window) {
    try {
      const options = {
        suggestedName: filename,
        types: [{
          description: extension === '.tex' ? 'Documento LaTeX' : 'Archivo de Texto',
          accept: {
            [mimeType]: [extension],
          },
        }],
      };
      const handle = await window.showSaveFilePicker(options);
      const writable = await handle.createWritable();
      await writable.write(content);
      await writable.close();
      showNotification('Archivo guardado correctamente en tu equipo.');
      setTimeout(hideNotification, 3000);
      return;
    } catch (err) {
      // User aborted the save dialog
      if (err.name === 'AbortError') {
        return;
      }
      console.error('showSaveFilePicker error, falling back...', err);
    }
  }

  // Fallback for browsers not supporting File System Access API
  const blob = new Blob([content], { type: mimeType + ';charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showNotification('Guardado como descarga en el navegador.');
  setTimeout(hideNotification, 3000);
}

function downloadTxt() {
  if (!lastTranscription) return;
  
  let baseSource = lastSource.split('/').pop().split('\\').pop() || 'transcripcion';
  let safeName = baseSource.replace(/[^a-zA-Z0-9\s_-]/g, '_').replace(/\s+/g, '_');
  if (!safeName) safeName = 'transcripcion';
  
  saveFileLocally(lastTranscription, safeName + '.txt', 'text/plain', '.txt');
}

function saveAsMd() {
  if (!lastTranscription) return;

  const payload = {
    transcription: lastTranscription,
    source: lastSource,
    model: lastModel,
    language: lastLanguage
  };

  fetch(getApiUrl('/api/save_md'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showNotification('Error al generar Markdown: ' + data.error, 'error');
    } else {
      saveFileLocally(data.content, data.filename, 'text/markdown', '.md');
    }
  })
  .catch(err => {
    let baseSource = lastSource.split('/').pop().split('\\').pop() || 'transcripcion';
    let safeName = baseSource.replace(/[^a-zA-Z0-9\s_-]/g, '_').replace(/\s+/g, '_');
    if (!safeName) safeName = 'transcripcion';
    const mdContent = `# Transcripción de Audio - AudioScribe\n\n- **Origen:** ${lastSource}\n\n---\n\n## Transcripción\n\n${lastTranscription}\n`;
    saveFileLocally(mdContent, safeName + '.md', 'text/markdown', '.md');
  });
}

function saveAsTex() {
  if (!lastTranscription) return;

  const payload = {
    transcription: lastTranscription,
    source: lastSource,
    model: lastModel,
    language: lastLanguage
  };

  fetch(getApiUrl('/api/save_tex'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showNotification('Error al generar LaTeX: ' + data.error, 'error');
    } else {
      saveFileLocally(data.content, data.filename, 'text/plain', '.tex');
    }
  })
  .catch(err => {
    showNotification('Error al conectar con la API: ' + err.message, 'error');
  });
}

// ==========================================
// FUNCIONES DE LA PESTAÑA CONVERTIDOR MP3
// ==========================================

let currentConvTab = 'conv-tab-link';
let conversionInterval = null;
let lastConvertedFilename = '';
let lastConvertedFilepath = '';

function showView(viewName) {
  document.getElementById('view-transcriptor').style.display = viewName === 'transcriptor' ? 'block' : 'none';
  document.getElementById('view-converter').style.display = viewName === 'converter' ? 'block' : 'none';
  document.getElementById('view-video-downloader').style.display = viewName === 'video-downloader' ? 'block' : 'none';
  document.getElementById('view-trimmer').style.display = viewName === 'trimmer' ? 'block' : 'none';
  document.getElementById('view-merger').style.display = viewName === 'merger' ? 'block' : 'none';

  document.getElementById('nav-btn-transcriptor').classList.toggle('is-active', viewName === 'transcriptor');
  document.getElementById('nav-btn-converter').classList.toggle('is-active', viewName === 'converter');
  document.getElementById('nav-btn-video-downloader').classList.toggle('is-active', viewName === 'video-downloader');
  document.getElementById('nav-btn-trimmer').classList.toggle('is-active', viewName === 'trimmer');
  document.getElementById('nav-btn-merger').classList.toggle('is-active', viewName === 'merger');
}

function updateBitrateValue(val) {
  document.getElementById('mp3-bitrate-display').textContent = val + ' kbps';
  
  // Quitar borde resaltado a presets activos
  document.querySelectorAll('[id^="preset-btn-"]').forEach(btn => {
    btn.style.borderColor = '';
    btn.style.color = '';
  });
  
  // Resaltar preset si coincide exactamente
  const presetBtn = document.getElementById('preset-btn-' + val);
  if (presetBtn) {
    presetBtn.style.borderColor = 'var(--accent)';
    presetBtn.style.color = 'var(--accent)';
  }

  // Texto de calidad descriptivo
  const qualityTag = document.getElementById('mp3-quality-tag');
  const bitrate = parseInt(val);
  if (bitrate < 192) {
    qualityTag.textContent = 'Calidad Estándar (ideal para voz, archivos compactos)';
    qualityTag.style.color = 'var(--muted)';
  } else if (bitrate < 256) {
    qualityTag.textContent = 'Calidad Buena (óptimo balance voz/música)';
    qualityTag.style.color = 'var(--accent)';
  } else if (bitrate < 320) {
    qualityTag.textContent = 'Calidad Alta (excelente nitidez sonora)';
    qualityTag.style.color = 'var(--patina)';
  } else {
    qualityTag.textContent = 'Calidad Extrema (estudio, máxima definición)';
    qualityTag.style.color = 'var(--accent-strong)';
  }
}

function setBitratePreset(val) {
  document.getElementById('mp3-bitrate-slider').value = val;
  updateBitrateValue(val);
}

function switchConvTab(tabId) {
  currentConvTab = tabId;
  const converterTabs = document.querySelector('#view-converter .tab-container');
  converterTabs.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('is-active');
  });
  document.getElementById('conv-tab-link').classList.remove('is-active');
  document.getElementById('conv-tab-local').classList.remove('is-active');
  
  const activeBtn = tabId === 'conv-tab-link' ? converterTabs.querySelectorAll('.tab-button')[0] : converterTabs.querySelectorAll('.tab-button')[1];
  activeBtn.classList.add('is-active');
  document.getElementById(tabId).classList.add('is-active');
}

function showConvNotification(message, type = 'success') {
  const notif = document.getElementById('conv-status-notification');
  notif.textContent = message;
  notif.className = 'notification ' + (type === 'success' ? 'notification--success' : 'notification--error');
  notif.style.display = 'block';
}

function hideConvNotification() {
  document.getElementById('conv-status-notification').style.display = 'none';
}

function downloadMp3File(filename) {
  window.location.href = getApiUrl('/api/download/mp3/' + encodeURIComponent(filename));
}

function loadIntoTranscriptor(absolutePath) {
  // 1. Cambiar a vista transcriptor
  showView('transcriptor');
  // 2. Seleccionar pestaña local
  switchTab('tab-local');
  // 3. Escribir ruta absoluta
  const localInput = document.getElementById('audio-local-path');
  localInput.value = absolutePath;
  
  // Resaltar visualmente el input
  localInput.style.transition = 'all 0.3s ease';
  localInput.style.borderColor = 'var(--patina)';
  localInput.style.boxShadow = '0 0 10px rgba(20, 184, 166, 0.4)';
  
  setTimeout(() => {
    localInput.style.borderColor = '';
    localInput.style.boxShadow = '';
  }, 2500);

  showNotification('MP3 cargado en el Transcriptor. Listo para procesar.');
  // Hacer scroll suave hacia el input
  localInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function startConversion() {
  hideConvNotification();
  document.getElementById('conv-placeholder-wrapper').style.display = 'none';
  document.getElementById('conv-result-wrapper').style.display = 'none';
  document.getElementById('conv-progress-wrapper').style.display = 'block';
  document.getElementById('btn-convert').disabled = true;

  const bitrate = document.getElementById('mp3-bitrate-slider').value;
  let payload = {
    bitrate: bitrate
  };

  if (currentConvTab === 'conv-tab-link') {
    const url = document.getElementById('conv-video-url').value;
    if (!url) {
      showConvError('Por favor, ingrese una URL válida.');
      return;
    }
    payload.source_type = 'url';
    payload.url = url;
    submitConversionJob(payload);
  } else {
    const localPath = document.getElementById('conv-video-local-path').value;
    const fileInput = document.getElementById('conv-local-file-picker');

    if (localPath) {
      payload.source_type = 'local_path';
      payload.local_path = localPath;
      submitConversionJob(payload);
    } else if (fileInput.files.length > 0) {
      payload.source_type = 'upload';
      uploadAndSubmitConversionJob(fileInput.files[0], payload);
    } else {
      showConvError('Debe ingresar una ruta absoluta o seleccionar un archivo para subir.');
    }
  }
}

function submitConversionJob(payload) {
  fetch(getApiUrl('/api/convert'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showConvError(data.error);
    } else {
      pollConversionStatus();
    }
  })
  .catch(err => {
    showConvError('Error de red al conectar con el backend: ' + err.message);
  });
}

function uploadAndSubmitConversionJob(file, payload) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('bitrate', payload.bitrate);
  formData.append('source_type', 'upload');

  document.getElementById('conv-progress-status').innerHTML = '<span class="progress-spinner"></span>Subiendo archivo...';
  document.getElementById('conv-progress-bar-fill').style.width = '10%';
  document.getElementById('conv-progress-percentage').textContent = '10%';

  fetch(getApiUrl('/api/convert'), {
    method: 'POST',
    body: formData
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      showConvError(data.error);
    } else {
      pollConversionStatus();
    }
  })
  .catch(err => {
    showConvError('Error de red durante la carga del archivo: ' + err.message);
  });
}

function showConvError(msg) {
  showConvNotification(msg, 'error');
  document.getElementById('conv-progress-wrapper').style.display = 'none';
  document.getElementById('conv-placeholder-wrapper').style.display = 'flex';
  document.getElementById('btn-convert').disabled = false;
  if (conversionInterval) clearInterval(conversionInterval);
  playErrorChime();
  loadFiles();
}

function pollConversionStatus() {
  if (conversionInterval) clearInterval(conversionInterval);

  conversionInterval = setInterval(() => {
    fetch(getApiUrl('/api/convert/status'))
    .then(res => res.json())
    .then(data => {
      document.getElementById('conv-progress-bar-fill').style.width = data.percent + '%';
      document.getElementById('conv-progress-percentage').textContent = data.percent + '%';
      document.getElementById('conv-progress-status').innerHTML = `<span class="progress-spinner"></span>${escapeHtml(data.message)}`;

      if (data.status === 'completed') {
        clearInterval(conversionInterval);
        displayConversionResult(data);
      } else if (data.status === 'error' || data.status === 'idle') {
        clearInterval(conversionInterval);
        showConvError(data.message);
      }
    })
    .catch(err => {
      console.error('Error polling conversion status:', err);
    });
  }, 1000);
}

function displayConversionResult(data) {
  document.getElementById('conv-progress-wrapper').style.display = 'none';
  document.getElementById('btn-convert').disabled = false;
  
  lastConvertedFilename = data.filename;
  lastConvertedFilepath = data.filepath;

  document.getElementById('conv-res-name').textContent = data.filename;
  document.getElementById('conv-res-quality').textContent = data.bitrate + ' kbps';
  document.getElementById('conv-res-size').textContent = data.filesize;
  document.getElementById('conv-res-path').textContent = data.filepath;
  
  document.getElementById('conv-result-wrapper').style.display = 'flex';
  showConvNotification('Conversión finalizada exitosamente.');
  loadFiles();
}

function downloadConvertedMP3() {
  if (lastConvertedFilename) {
    downloadMp3File(lastConvertedFilename);
  }
}

function sendMP3ToTranscriptor() {
  if (lastConvertedFilepath) {
    loadIntoTranscriptor(lastConvertedFilepath);
  }
}

// Sincronización de inputs de archivo para evitar conflictos
document.getElementById('local-file-picker').addEventListener('change', function() {
  if (this.files.length > 0) {
    document.getElementById('audio-local-path').value = '';
  }
});
document.getElementById('audio-local-path').addEventListener('input', function() {
  if (this.value.trim() !== '') {
    document.getElementById('local-file-picker').value = '';
  }
});

document.getElementById('conv-local-file-picker').addEventListener('change', function() {
  if (this.files.length > 0) {
    document.getElementById('conv-video-local-path').value = '';
  }
});
document.getElementById('conv-video-local-path').addEventListener('input', function() {
  if (this.value.trim() !== '') {
    document.getElementById('conv-local-file-picker').value = '';
  }
});

// ==========================================
// FUNCIONES DE LA PESTAÑA DESCARGAR VIDEOS
// ==========================================
let videoPollInterval = null;

function showVideoNotification(message, type = 'success') {
  const notif = document.getElementById('video-notification');
  notif.textContent = message;
  notif.className = 'notification ' + (type === 'success' ? 'notification--success' : 'notification--error');
  notif.style.display = 'block';
}

function hideVideoNotification() {
  document.getElementById('video-notification').style.display = 'none';
}

function startVideoDownload() {
  const quality = document.getElementById('video-quality-select').value;
  const tasks = [];

  if (isVideoBatchMode) {
    const rawUrls = document.getElementById('video-url-batch').value.split('\n');
    const urls = rawUrls.map(u => u.trim()).filter(u => u.length > 0);
    if (urls.length === 0) {
      showVideoNotification('Por favor ingresa al menos una URL válida en la lista por lotes.', 'error');
      return;
    }
    for (let url of urls) {
      tasks.push({
        type: 'video_download',
        source_type: 'url',
        title: 'Video YT: ' + (url.length > 40 ? url.substring(0, 37) + '...' : url),
        payload: { url, quality }
      });
    }
  } else {
    const url = document.getElementById('video-download-url').value.trim();
    if (!url) {
      showVideoNotification('Por favor ingresa una URL válida de YouTube.', 'error');
      return;
    }
    tasks.push({
      type: 'video_download',
      source_type: 'url',
      title: 'Video YT: ' + (url.length > 40 ? url.substring(0, 37) + '...' : url),
      payload: { url, quality }
    });
  }

  addTasksToQueue(tasks);
}

function pollVideoDownloadProgress() {
  if (videoPollInterval) clearInterval(videoPollInterval);
  
  videoPollInterval = setInterval(async () => {
    try {
      const res = await fetch(getApiUrl('/api/download_video/status'));
      const data = await res.json();
      
      document.getElementById('video-progress-bar-fill').style.width = `${data.percent}%`;
      document.getElementById('video-progress-percentage').innerText = `${data.percent}%`;
      document.getElementById('video-progress-status').innerHTML = `<span class="progress-spinner"></span>${escapeHtml(data.message)}`;
      
      if (data.status === 'completed') {
        clearInterval(videoPollInterval);
        document.getElementById('video-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-video-download').disabled = false;
        
        document.getElementById('video-result-filename').innerText = data.filename;
        document.getElementById('video-result-filesize').innerText = data.filesize;
        document.getElementById('video-output-directory').innerText = data.filepath;
        
        const dlBtn = document.getElementById('btn-download-video-file');
        dlBtn.href = getApiUrl(`/api/download_video/file/${encodeURIComponent(data.filename)}`);
        dlBtn.download = data.filename;
        
        document.getElementById('video-result-wrapper').style.display = 'flex';
        showVideoNotification('¡Video descargado exitosamente en MP4!', 'success');
        loadFiles();
      } else if (data.status === 'error' || data.status === 'idle') {
        clearInterval(videoPollInterval);
        document.getElementById('video-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-video-download').disabled = false;
        document.getElementById('video-placeholder-wrapper').style.display = 'flex';
        showVideoNotification(data.message, 'error');
      }
    } catch (e) {
      console.error('Error sondeando estado de descarga de video:', e);
    }
  }, 1000);
}

async function cancelVideoDownload() {
  if (videoPollInterval) clearInterval(videoPollInterval);
  try {
    await fetch(getApiUrl('/api/download_video/cancel'), { method: 'POST' });
  } catch (e) {}
  document.getElementById('video-progress-wrapper').style.display = 'none';
  document.getElementById('btn-start-video-download').disabled = false;
  document.getElementById('video-placeholder-wrapper').style.display = 'flex';
  showVideoNotification('Descarga de video cancelada.', 'error');
}

// ==========================================
// FUNCIONES DE LA PESTAÑA RECORTADOR
// ==========================================
let currentTrimTab = 'trim-tab-link';
let trimPollInterval = null;
let lastTrimmedFilename = '';
let lastTrimmedFilepath = '';

function switchTrimTab(tabId) {
  currentTrimTab = tabId;
  const trimTabs = document.querySelector('#view-trimmer .tab-container');
  trimTabs.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('is-active');
  });
  document.getElementById('trim-tab-link').classList.remove('is-active');
  document.getElementById('trim-tab-local').classList.remove('is-active');
  
  const btnIndex = tabId === 'trim-tab-link' ? 0 : 1;
  trimTabs.querySelectorAll('.tab-button')[btnIndex].classList.add('is-active');
  document.getElementById(tabId).classList.add('is-active');
}

function showTrimNotification(message, type = 'success') {
  const notif = document.getElementById('trim-notification');
  notif.textContent = message;
  notif.className = 'notification ' + (type === 'success' ? 'notification--success' : 'notification--error');
  notif.style.display = 'block';
}

function hideTrimNotification() {
  document.getElementById('trim-notification').style.display = 'none';
}

async function startTrim() {
  hideTrimNotification();
  document.getElementById('trim-placeholder-wrapper').style.display = 'none';
  document.getElementById('trim-result-wrapper').style.display = 'none';
  document.getElementById('trim-progress-wrapper').style.display = 'block';
  document.getElementById('btn-start-trim').disabled = true;

  const format = document.getElementById('trim-format-select').value;
  const startTime = document.getElementById('trim-start-time').value.trim() || '00:00:00';
  const endTime = document.getElementById('trim-end-time').value.trim() || '00:01:00';

  try {
    let reqPromise;

    if (currentTrimTab === 'trim-tab-link') {
      const url = document.getElementById('trim-url').value.trim();
      if (!url) {
        throw new Error('Por favor ingresa una URL válida de YouTube.');
      }
      reqPromise = fetch(getApiUrl('/api/trim'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: 'url',
          url: url,
          start_time: startTime,
          end_time: endTime,
          format: format
        })
      });
    } else {
      const localFile = document.getElementById('trim-local-file-picker').files[0];
      const localPath = document.getElementById('trim-video-local-path').value.trim();

      if (localFile) {
        const formData = new FormData();
        formData.append('file', localFile);
        formData.append('start_time', startTime);
        formData.append('end_time', endTime);
        formData.append('format', format);

        reqPromise = fetch(getApiUrl('/api/trim'), {
          method: 'POST',
          body: formData
        });
      } else if (localPath) {
        reqPromise = fetch(getApiUrl('/api/trim'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_type: 'local_path',
            local_path: localPath,
            start_time: startTime,
            end_time: endTime,
            format: format
          })
        });
      } else {
        throw new Error('Debe seleccionar un archivo local o ingresar una ruta válida.');
      }
    }

    const res = await reqPromise;
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Error al iniciar el recorte.');

    pollTrimProgress();
  } catch (err) {
    document.getElementById('trim-progress-wrapper').style.display = 'none';
    document.getElementById('btn-start-trim').disabled = false;
    document.getElementById('trim-placeholder-wrapper').style.display = 'flex';
    showTrimNotification(err.message, 'error');
  }
}

function pollTrimProgress() {
  if (trimPollInterval) clearInterval(trimPollInterval);

  trimPollInterval = setInterval(async () => {
    try {
      const res = await fetch(getApiUrl('/api/trim/status'));
      const data = await res.json();

      document.getElementById('trim-progress-bar-fill').style.width = `${data.percent}%`;
      document.getElementById('trim-progress-percentage').innerText = `${data.percent}%`;
      document.getElementById('trim-progress-status').innerHTML = `<span class="progress-spinner"></span>${escapeHtml(data.message)}`;

      if (data.status === 'completed') {
        clearInterval(trimPollInterval);
        document.getElementById('trim-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-trim').disabled = false;

        lastTrimmedFilename = data.filename;
        lastTrimmedFilepath = data.filepath;

        document.getElementById('trim-res-name').innerText = data.filename;
        document.getElementById('trim-res-size').innerText = data.filesize;
        document.getElementById('trim-res-path').innerText = data.filepath;

        const dlBtn = document.getElementById('btn-trim-download');
        dlBtn.href = getApiUrl(`/api/trim/file/${encodeURIComponent(data.filename)}`);
        dlBtn.download = data.filename;

        document.getElementById('trim-result-wrapper').style.display = 'flex';
        showTrimNotification('¡Fragmento recortado exitosamente!', 'success');
        playCompletionChime();
        loadFiles();
      } else if (data.status === 'error' || data.status === 'idle') {
        clearInterval(trimPollInterval);
        document.getElementById('trim-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-trim').disabled = false;
        document.getElementById('trim-placeholder-wrapper').style.display = 'flex';
        showTrimNotification(data.message, 'error');
        playErrorChime();
      }
    } catch (e) {
      console.error('Error sondeando estado de recorte:', e);
    }
  }, 1000);
}

async function cancelTrim() {
  if (trimPollInterval) clearInterval(trimPollInterval);
  try {
    await fetch(getApiUrl('/api/trim/cancel'), { method: 'POST' });
  } catch (e) {}
  document.getElementById('trim-progress-wrapper').style.display = 'none';
  document.getElementById('btn-start-trim').disabled = false;
  document.getElementById('trim-placeholder-wrapper').style.display = 'flex';
  showTrimNotification('Recorte cancelado.', 'error');
}

function sendTrimToTranscriptor() {
  if (lastTrimmedFilepath) {
    loadIntoTranscriptor(lastTrimmedFilepath);
  }
}

document.getElementById('trim-local-file-picker').addEventListener('change', function() {
  if (this.files.length > 0) {
    document.getElementById('trim-video-local-path').value = '';
  }
});
document.getElementById('trim-video-local-path').addEventListener('input', function() {
  if (this.value.trim() !== '') {
    document.getElementById('trim-local-file-picker').value = '';
  }
});

// ==========================================
// FUNCIONES DE LA PESTAÑA FUSIONADOR
// ==========================================
let mergeSelectedFiles = []; // Array de { id, name, fileObj, path }
let mergePollInterval = null;
let lastMergedFilename = '';
let lastMergedFilepath = '';

function handleMergeFilesSelect(files) {
  if (!files || files.length === 0) return;
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    mergeSelectedFiles.push({
      id: 'file_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
      name: f.name,
      fileObj: f,
      path: null
    });
  }
  renderMergeItems();
}

function addExistingFileToMerge(name, path) {
  mergeSelectedFiles.push({
    id: 'path_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
    name: name,
    fileObj: null,
    path: path
  });
  renderMergeItems();
  showNotification(`Añadido "${name}" a la lista de fusión.`);
}

function renderMergeItems() {
  const container = document.getElementById('merge-items-container');
  if (!container) return;

  if (mergeSelectedFiles.length === 0) {
    container.innerHTML = `<div class="muted" style="text-align: center; padding: 2rem 1rem;">No hay archivos seleccionados para fusionar.</div>`;
    return;
  }

  container.innerHTML = mergeSelectedFiles.map((item, idx) => `
    <div style="display: flex; justify-content: space-between; align-items: center; background: var(--panel); padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid var(--border); font-size: 0.88rem;">
      <div style="display: flex; align-items: center; gap: 0.5rem; min-width: 0; flex-grow: 1; padding-right: 0.5rem;">
        <span style="font-weight: 600; color: var(--accent); flex-shrink: 0;">#${idx + 1}</span>
        <span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--accent-strong);" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
      </div>
      <div style="display: flex; gap: 0.2rem; flex-shrink: 0; align-items: center;">
        <button class="btn btn--ghost" style="padding: 0.2rem 0.4rem; font-size: 0.8rem;" onclick="moveMergeItem(${idx}, -1)" ${idx === 0 ? 'disabled style="opacity: 0.3;"' : ''} title="Mover arriba">
          ⬆️
        </button>
        <button class="btn btn--ghost" style="padding: 0.2rem 0.4rem; font-size: 0.8rem;" onclick="moveMergeItem(${idx}, 1)" ${idx === mergeSelectedFiles.length - 1 ? 'disabled style="opacity: 0.3;"' : ''} title="Mover abajo">
          ⬇️
        </button>
        <button class="btn btn--ghost" style="padding: 0.2rem 0.4rem; font-size: 0.8rem; color: #d9534f;" onclick="removeMergeItem(${idx})" title="Quitar de la lista">
          ❌
        </button>
      </div>
    </div>
  `).join('');
}

function moveMergeItem(index, direction) {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= mergeSelectedFiles.length) return;
  const temp = mergeSelectedFiles[index];
  mergeSelectedFiles[index] = mergeSelectedFiles[newIndex];
  mergeSelectedFiles[newIndex] = temp;
  renderMergeItems();
}

function removeMergeItem(index) {
  mergeSelectedFiles.splice(index, 1);
  renderMergeItems();
}

function showMergeNotification(message, type = 'success') {
  const notif = document.getElementById('merge-notification');
  notif.textContent = message;
  notif.className = 'notification ' + (type === 'success' ? 'notification--success' : 'notification--error');
  notif.style.display = 'block';
}

function hideMergeNotification() {
  document.getElementById('merge-notification').style.display = 'none';
}

async function startMerge() {
  if (mergeSelectedFiles.length < 2) {
    showMergeNotification('Por favor añade al menos 2 archivos para realizar la fusión.', 'error');
    return;
  }

  hideMergeNotification();
  document.getElementById('merge-placeholder-wrapper').style.display = 'none';
  document.getElementById('merge-result-wrapper').style.display = 'none';
  document.getElementById('merge-progress-wrapper').style.display = 'block';
  document.getElementById('btn-start-merge').disabled = true;

  const format = document.getElementById('merge-format-select').value;

  try {
    const hasFileObjs = mergeSelectedFiles.some(item => item.fileObj !== null);
    const hasPathsOnly = mergeSelectedFiles.every(item => item.path !== null);

    let reqPromise;

    if (hasFileObjs) {
      const formData = new FormData();
      formData.append('format', format);
      for (let item of mergeSelectedFiles) {
        if (item.fileObj) {
          formData.append('files', item.fileObj);
        }
      }
      reqPromise = fetch(getApiUrl('/api/merge'), {
        method: 'POST',
        body: formData
      });
    } else if (hasPathsOnly) {
      const paths = mergeSelectedFiles.map(item => item.path);
      reqPromise = fetch(getApiUrl('/api/merge'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths, format })
      });
    } else {
      throw new Error('Formato de archivos mixto no soportado directamente. Por favor suba los archivos de la PC juntos.');
    }

    const res = await reqPromise;
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Error al iniciar la fusión.');

    pollMergeProgress();
  } catch (err) {
    document.getElementById('merge-progress-wrapper').style.display = 'none';
    document.getElementById('btn-start-merge').disabled = false;
    document.getElementById('merge-placeholder-wrapper').style.display = 'flex';
    showMergeNotification(err.message, 'error');
  }
}

function pollMergeProgress() {
  if (mergePollInterval) clearInterval(mergePollInterval);

  mergePollInterval = setInterval(async () => {
    try {
      const res = await fetch(getApiUrl('/api/merge/status'));
      const data = await res.json();

      document.getElementById('merge-progress-bar-fill').style.width = `${data.percent}%`;
      document.getElementById('merge-progress-percentage').innerText = `${data.percent}%`;
      document.getElementById('merge-progress-status').innerHTML = `<span class="progress-spinner"></span>${escapeHtml(data.message)}`;

      if (data.status === 'completed') {
        clearInterval(mergePollInterval);
        document.getElementById('merge-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-merge').disabled = false;

        lastMergedFilename = data.filename;
        lastMergedFilepath = data.filepath;

        document.getElementById('merge-res-name').innerText = data.filename;
        document.getElementById('merge-res-size').innerText = data.filesize;
        document.getElementById('merge-res-path').innerText = data.filepath;

        const dlBtn = document.getElementById('btn-merge-download');
        dlBtn.href = getApiUrl(`/api/merge/file/${encodeURIComponent(data.filename)}`);
        dlBtn.download = data.filename;

        document.getElementById('merge-result-wrapper').style.display = 'flex';
        showMergeNotification('¡Archivos fusionados exitosamente!', 'success');
        playCompletionChime();
        loadFiles();
      } else if (data.status === 'error' || data.status === 'idle') {
        clearInterval(mergePollInterval);
        document.getElementById('merge-progress-wrapper').style.display = 'none';
        document.getElementById('btn-start-merge').disabled = false;
        document.getElementById('merge-placeholder-wrapper').style.display = 'flex';
        showMergeNotification(data.message, 'error');
        playErrorChime();
      }
    } catch (e) {
      console.error('Error sondeando estado de fusión:', e);
    }
  }, 1000);
}

async function cancelMerge() {
  if (mergePollInterval) clearInterval(mergePollInterval);
  try {
    await fetch(getApiUrl('/api/merge/cancel'), { method: 'POST' });
  } catch (e) {}
  document.getElementById('merge-progress-wrapper').style.display = 'none';
  document.getElementById('btn-start-merge').disabled = false;
  document.getElementById('merge-placeholder-wrapper').style.display = 'flex';
  showMergeNotification('Fusión cancelada.', 'error');
}

function loadIntoTranscriptor(filepath) {
  showView('transcriptor');
  switchTab('tab-local');
  document.getElementById('audio-local-path').value = filepath;
  document.getElementById('local-file-picker').value = '';
  showNotification(`Ruta cargada en Transcriptor: ${filepath}`);
}

function sendMergeToTranscriptor() {
  if (lastMergedFilepath) {
    loadIntoTranscriptor(lastMergedFilepath);
  }
}

// ==========================================
// REPRODUCTOR DE TRANSCRIPCIÓN (TTS) Y ESTADÍSTICAS
// ==========================================
let ttsUtterance = null;
let ttsVoices = [];
let selectedVoiceIndex = -1;

function initTTSVoices() {
  if ('speechSynthesis' in window) {
    const loadVoices = () => {
      ttsVoices = window.speechSynthesis.getVoices();
      const voiceSelect = document.getElementById('tts-voice-select');
      if (!voiceSelect) return;

      if (!ttsVoices || ttsVoices.length === 0) {
        voiceSelect.innerHTML = `<option value="">Voz predeterminada del sistema</option>`;
        return;
      }

      voiceSelect.innerHTML = ttsVoices.map((v, i) => {
        const isEs = v.lang.startsWith('es');
        return `<option value="${i}" ${isEs && selectedVoiceIndex === -1 ? 'selected' : ''}>${v.name} (${v.lang})</option>`;
      }).join('');

      const firstEsIdx = ttsVoices.findIndex(v => v.lang.startsWith('es'));
      if (firstEsIdx !== -1 && selectedVoiceIndex === -1) {
        selectedVoiceIndex = firstEsIdx;
      }
    };

    loadVoices();
    if (window.speechSynthesis.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }
}

function playTranscriptionTTS() {
  if (!('speechSynthesis' in window)) {
    showNotification('Tu navegador no soporta síntesis de voz.', 'error');
    return;
  }

  const text = document.getElementById('transcription-text')?.textContent || '';
  if (!text || text.trim() === '') {
    showNotification('No hay transcripción disponible para reproducir.', 'error');
    return;
  }

  if (window.speechSynthesis.paused) {
    window.speechSynthesis.resume();
    document.getElementById('btn-tts-play').style.display = 'none';
    document.getElementById('btn-tts-pause').style.display = 'inline-flex';
    return;
  }

  window.speechSynthesis.cancel();
  ttsUtterance = new SpeechSynthesisUtterance(text);
  ttsUtterance.rate = parseFloat(document.getElementById('tts-rate-select').value) || 1;

  const voiceIdx = document.getElementById('tts-voice-select').value;
  if (voiceIdx !== '' && ttsVoices[voiceIdx]) {
    ttsUtterance.voice = ttsVoices[voiceIdx];
  }

  ttsUtterance.onstart = () => {
    document.getElementById('btn-tts-play').style.display = 'none';
    document.getElementById('btn-tts-pause').style.display = 'inline-flex';
  };

  ttsUtterance.onend = () => {
    document.getElementById('btn-tts-play').style.display = 'inline-flex';
    document.getElementById('btn-tts-pause').style.display = 'none';
  };

  ttsUtterance.onerror = (e) => {
    console.error('Error TTS:', e);
    document.getElementById('btn-tts-play').style.display = 'inline-flex';
    document.getElementById('btn-tts-pause').style.display = 'none';
  };

  window.speechSynthesis.speak(ttsUtterance);
}

function pauseTranscriptionTTS() {
  if (window.speechSynthesis && window.speechSynthesis.speaking) {
    window.speechSynthesis.pause();
    document.getElementById('btn-tts-play').style.display = 'inline-flex';
    document.getElementById('btn-tts-pause').style.display = 'none';
  }
}

function stopTranscriptionTTS() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
    document.getElementById('btn-tts-play').style.display = 'inline-flex';
    document.getElementById('btn-tts-pause').style.display = 'none';
  }
}

function updateTTSRate(rate) {
  if (window.speechSynthesis && window.speechSynthesis.speaking) {
    stopTranscriptionTTS();
    playTranscriptionTTS();
  }
}

function changeTTSVoice(val) {
  selectedVoiceIndex = parseInt(val);
  if (window.speechSynthesis && window.speechSynthesis.speaking) {
    stopTranscriptionTTS();
    playTranscriptionTTS();
  }
}

function analyzeTranscriptionStats(text) {
  if (!text || text.trim() === '') {
    document.getElementById('stat-words-count').textContent = '0';
    document.getElementById('stat-chars-count').textContent = '0';
    document.getElementById('stat-wpm').textContent = '- PPM';
    document.getElementById('stat-keywords-tags').innerHTML = `<span class="muted" style="font-size: 0.8rem;">Sin datos</span>`;
    return;
  }

  const cleanText = text.trim();
  const words = cleanText.split(/\s+/).filter(w => w.length > 0);
  const wordCount = words.length;
  const charCount = cleanText.length;

  // Estimación de velocidad promedio de habla en PPM
  const wpmDisplay = wordCount > 0 ? `~150 PPM` : '- PPM';

  document.getElementById('stat-words-count').textContent = wordCount.toLocaleString();
  document.getElementById('stat-chars-count').textContent = charCount.toLocaleString();
  document.getElementById('stat-wpm').textContent = wpmDisplay;

  // Filtrar conectores y stop words en español e inglés para extraer palabras clave
  const stopWords = new Set([
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'e', 'ni', 'que', 'o', 'u', 'pero', 'mas', 'si',
    'para', 'por', 'con', 'en', 'de', 'del', 'a', 'al', 'ante', 'bajo', 'cabe', 'con', 'contra', 'desde', 'sin',
    'sobre', 'tras', 'es', 'son', 'fue', 'fueron', 'ser', 'estar', 'ha', 'han', 'hay', 'esto', 'esta', 'este',
    'estos', 'estas', 'como', 'cuando', 'donde', 'quien', 'cual', 'que', 'su', 'sus', 'mi', 'mis', 'tu', 'tus',
    'nosotros', 'ellos', 'ellas', 'ustedes', 'the', 'and', 'to', 'of', 'a', 'in', 'is', 'it', 'you', 'that', 'this',
    'como', 'para', 'pero', 'tambien', 'estos', 'esta', 'estos', 'entre'
  ]);

  const freqMap = {};
  for (let w of words) {
    const norm = w.toLowerCase().replace(/[^\wáéíóúñ]/g, '');
    if (norm.length > 3 && !stopWords.has(norm)) {
      freqMap[norm] = (freqMap[norm] || 0) + 1;
    }
  }

  const sortedKeywords = Object.entries(freqMap)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  if (sortedKeywords.length === 0) {
    document.getElementById('stat-keywords-tags').innerHTML = `<span class="muted" style="font-size: 0.8rem;">No se detectaron palabras clave significativas.</span>`;
  } else {
    document.getElementById('stat-keywords-tags').innerHTML = sortedKeywords.map(([kw, count]) => `
      <span class="badge" style="background: var(--accent-pale); color: var(--accent-calm); border-color: var(--accent); font-weight: 600; text-transform: none; font-size: 0.82rem;">
        🏷️ ${kw} (${count})
      </span>
    `).join('');
  }
}

// ==========================================
// SISTEMA DE NOTIFICACIÓN SONORA (WEB AUDIO API)
// ==========================================
let isSoundEnabled = localStorage.getItem('sound_enabled') !== 'false';

function updateSoundIcon() {
  const btn = document.getElementById('sound-toggle-btn');
  if (btn) {
    btn.textContent = isSoundEnabled ? '🔔' : '🔕';
    btn.title = isSoundEnabled ? 'Sonido de notificación activado' : 'Sonido de notificación desactivado';
  }
}

function toggleSoundNotification() {
  isSoundEnabled = !isSoundEnabled;
  localStorage.setItem('sound_enabled', isSoundEnabled);
  updateSoundIcon();
  if (isSoundEnabled) {
    playCompletionChime();
    showNotification('Notificaciones sonoras activadas.');
  } else {
    showNotification('Notificaciones sonoras desactivadas.');
  }
  setTimeout(hideNotification, 2000);
}

function playCompletionChime() {
  if (!isSoundEnabled) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();

    // Acorde armónico ascendente (C5 -> E5 -> G5)
    const notes = [523.25, 659.25, 783.99];
    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.value = freq;

      const startTime = ctx.currentTime + idx * 0.1;
      const duration = 0.35;

      gain.gain.setValueAtTime(0.01, startTime);
      gain.gain.exponentialRampToValueAtTime(0.2, startTime + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(startTime);
      osc.stop(startTime + duration);
    });
  } catch (e) {
    console.error('Error al reproducir tono de notificación:', e);
  }
}

function playErrorChime() {
  if (!isSoundEnabled) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();

    const notes = [400, 300];
    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'triangle';
      osc.frequency.value = freq;

      const startTime = ctx.currentTime + idx * 0.15;
      const duration = 0.3;

      gain.gain.setValueAtTime(0.01, startTime);
      gain.gain.exponentialRampToValueAtTime(0.18, startTime + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(startTime);
      osc.stop(startTime + duration);
    });
  } catch (e) {}
}
