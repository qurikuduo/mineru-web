/* ============ MinerU Web Console — frontend logic ============ */
(function () {
  'use strict';

  // ---- state ----
  const state = {
    token: localStorage.getItem('mineru_web_token') || null,
    username: localStorage.getItem('mineru_web_username') || null,
    files: [],           // { file, name, size }
    tier: 'flash',
    format: 'default',
    pollTimer: null,
  };

  // ---- dom ----
  const $ = (id) => document.getElementById(id);
  const els = {
    loginView: $('login-view'),
    appView: $('app-view'),
    loginForm: $('login-form'),
    loginUsername: $('login-username'),
    loginPassword: $('login-password'),
    loginError: $('login-error'),
    currentUser: $('current-user'),
    mineruStatus: $('mineru-status'),
    mineruStatusText: $('mineru-status-text'),
    dropzone: $('dropzone'),
    fileInput: $('file-input'),
    selectedFiles: $('selected-files'),
    tierSelect: $('tier-select'),
    formatSelect: $('format-select'),
    btnSubmit: $('btn-submit'),
    btnSubmitLabel: $('btn-submit-label'),
    tasksList: $('tasks-list'),
    settingsModal: $('settings-modal'),
    cfgUrl: $('cfg-url'),
    cfgUsername: $('cfg-username'),
    cfgPassword: $('cfg-password'),
    btnTest: $('btn-test'),
    testResult: $('test-result'),
    btnSaveConfig: $('btn-save-config'),
    btnLogout: $('btn-logout'),
    btnSettings: $('btn-settings'),
    btnTheme: $('btn-theme'),
    btnThemeLogin: $('btn-theme-login'),
    appVersion: $('app-version'),
    loginVersion: $('login-version'),
  };

  // ---- toast ----
  let toastWrap = null;
  function toast(msg, type) {
    if (!toastWrap) {
      toastWrap = document.createElement('div');
      toastWrap.className = 'toast-wrap';
      document.body.appendChild(toastWrap);
    }
    const t = document.createElement('div');
    t.className = 'toast' + (type ? ' ' + type : '');
    t.textContent = msg;
    toastWrap.appendChild(t);
    setTimeout(() => t.remove(), 3200);
  }

  // ---- theme ----
  const THEME_KEY = 'mineru_web_theme';
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
  }
  function initTheme() {
    let t = 'dark';
    try { t = localStorage.getItem(THEME_KEY) || 'dark'; } catch (e) {}
    if (t !== 'light' && t !== 'dark') t = 'dark';
    applyTheme(t);
  }
  function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(cur === 'dark' ? 'light' : 'dark');
  }

  // ---- version ----
  async function loadVersion() {
    try {
      const res = await fetch('/api/health');
      const d = await res.json().catch(() => ({}));
      if (d && d.version) {
        const v = 'v' + d.version;
        if (els.appVersion) els.appVersion.textContent = v;
        if (els.loginVersion) els.loginVersion.textContent = v;
      }
    } catch (e) {}
  }

  // ---- api ----
  function authHeaders() {
    return state.token ? { Authorization: 'Bearer ' + state.token } : {};
  }

  async function request(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers, authHeaders());
    const res = await fetch(url, opts);
    if (res.status === 401) {
      logout(false);
      throw new Error('未登录或会话已过期');
    }
    return res;
  }

  async function getJSON(url) {
    const res = await request(url);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || ('请求失败 (' + res.status + ')'));
    }
    return res.json();
  }

  // ---- view switching ----
  function showLogin() {
    els.appView.classList.add('hidden');
    els.loginView.classList.remove('hidden');
  }
  function showApp() {
    els.loginView.classList.add('hidden');
    els.appView.classList.remove('hidden');
  }

  function logout(clearStorage) {
    state.token = null;
    state.username = null;
    if (clearStorage !== false) {
      localStorage.removeItem('mineru_web_token');
      localStorage.removeItem('mineru_web_username');
    }
    stopPolling();
    showLogin();
  }

  // ---- auth ----
  async function handleLogin(e) {
    e.preventDefault();
    const username = els.loginUsername.value.trim();
    const password = els.loginPassword.value;
    els.loginError.textContent = '';
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        els.loginError.textContent = data.detail || '登录失败';
        return;
      }
      state.token = data.token;
      state.username = data.username;
      localStorage.setItem('mineru_web_token', data.token);
      localStorage.setItem('mineru_web_username', data.username);
      els.loginPassword.value = '';
      els.currentUser.textContent = data.username;
      showApp();
      await Promise.all([loadConfig(), refreshTasks(), checkMineruStatus()]);
      startPolling();
    } catch (err) {
      els.loginError.textContent = '网络错误：' + err.message;
    }
  }

  // ---- config ----
  async function loadConfig() {
    try {
      const cfg = await getJSON('/api/config');
      els.cfgUrl.value = cfg.mineru_base_url || '';
      els.cfgUsername.value = cfg.username || '';
      if (cfg.defaults) {
        if (cfg.defaults.tier) setTier(cfg.defaults.tier);
        const fmts = cfg.defaults.output_formats;
        if (Array.isArray(fmts) && fmts.length) setFormat(fmts[0]);
      }
    } catch (e) {
      toast('加载配置失败：' + e.message, 'error');
    }
  }

  function setTier(tier) {
    state.tier = tier;
    els.tierSelect.querySelectorAll('.seg').forEach((b) => {
      b.classList.toggle('active', b.dataset.tier === tier);
    });
  }

  function setFormat(fmt) {
    state.format = fmt;
    els.formatSelect.querySelectorAll('.chip').forEach((b) => {
      b.classList.toggle('active', b.dataset.fmt === fmt);
    });
  }

  async function checkMineruStatus() {
    els.mineruStatus.classList.remove('ok', 'bad');
    els.mineruStatusText.textContent = '检测中…';
    try {
      const res = await request('/api/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mineru_base_url: els.cfgUrl.value || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        els.mineruStatus.classList.add('ok');
        els.mineruStatus.classList.remove('bad');
        els.mineruStatusText.textContent = '已连接';
        toast('MinerU 连接正常' + (data.version ? '（' + data.version + '）' : ''));
      } else {
        els.mineruStatus.classList.add('bad');
        els.mineruStatus.classList.remove('ok');
        els.mineruStatusText.textContent = '连接失败';
        toast('MinerU 连接失败：' + (data.error || '未知错误'), 'error');
      }
    } catch (e) {
      els.mineruStatus.classList.add('bad');
      els.mineruStatus.classList.remove('ok');
      els.mineruStatusText.textContent = '连接失败';
    }
  }

  async function handleTestConfig() {
    els.testResult.textContent = '测试中…';
    els.testResult.className = 'test-result';
    try {
      const res = await request('/api/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mineru_base_url: els.cfgUrl.value.trim() || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        els.testResult.textContent = '✓ 连接成功' + (data.version ? '（' + data.version + '）' : '');
        els.testResult.className = 'test-result ok';
      } else {
        els.testResult.textContent = '✗ ' + (data.error || '连接失败');
        els.testResult.className = 'test-result bad';
      }
    } catch (e) {
      els.testResult.textContent = '✗ ' + e.message;
      els.testResult.className = 'test-result bad';
    }
  }

  async function handleSaveConfig() {
    const payload = { mineru_base_url: els.cfgUrl.value.trim() };
    if (els.cfgUsername.value.trim()) payload.username = els.cfgUsername.value.trim();
    if (els.cfgPassword.value) payload.password = els.cfgPassword.value;
    try {
      await getJSON('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      toast('配置已保存');
      closeModal();
      await checkMineruStatus();
    } catch (e) {
      toast('保存失败：' + e.message, 'error');
    }
  }

  // ---- modal ----
  function openModal() {
    els.cfgPassword.value = '';
    els.testResult.textContent = '';
    els.settingsModal.classList.remove('hidden');
  }
  function closeModal() {
    els.settingsModal.classList.add('hidden');
  }

  // ---- files ----
  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  function addFiles(fileList) {
    for (const file of fileList) {
      state.files.push({ file, name: file.name, size: file.size });
    }
    renderSelectedFiles();
  }

  function removeFile(index) {
    state.files.splice(index, 1);
    renderSelectedFiles();
  }

  function renderSelectedFiles() {
    els.selectedFiles.innerHTML = '';
    if (!state.files.length) {
      els.selectedFiles.classList.add('hidden');
      return;
    }
    els.selectedFiles.classList.remove('hidden');
    state.files.forEach((f, i) => {
      const chip = document.createElement('div');
      chip.className = 'file-chip';
      const name = document.createElement('span');
      name.className = 'fname';
      name.textContent = f.name;
      name.title = f.name;
      const size = document.createElement('span');
      size.className = 'fsize';
      size.textContent = fmtSize(f.size);
      const del = document.createElement('span');
      del.className = 'fdel';
      del.textContent = '×';
      del.title = '移除';
      del.addEventListener('click', () => removeFile(i));
      chip.appendChild(name);
      chip.appendChild(size);
      chip.appendChild(del);
      els.selectedFiles.appendChild(chip);
    });
  }

  // ---- submit ----
  async function handleSubmit() {
    if (!state.files.length) {
      toast('请先选择要转换的文件', 'error');
      return;
    }
    const fd = new FormData();
    state.files.forEach((f) => fd.append('files', f.file, f.file.name));
    fd.append('tier', state.tier);
    fd.append('output_formats', state.format);

    els.btnSubmit.disabled = true;
    els.btnSubmitLabel.textContent = '提交中…';
    try {
      const res = await request('/api/tasks', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || ('提交失败 (' + res.status + ')'));
      toast('任务已创建：' + data.id);
      state.files = [];
      renderSelectedFiles();
      els.fileInput.value = '';
      await refreshTasks();
    } catch (e) {
      toast('提交失败：' + e.message, 'error');
    } finally {
      els.btnSubmit.disabled = false;
      els.btnSubmitLabel.textContent = '开始转换';
    }
  }

  // ---- tasks ----
  const STATUS_LABEL = {
    uploading: '上传中',
    running: '处理中',
    completed: '已完成',
    partial: '部分完成',
    failed: '失败',
    canceled: '已取消',
  };
  const FILE_STATUS_LABEL = {
    'waiting-file': '等待上传',
    pending: '待处理',
    running: '处理中',
    completed: '完成',
    failed: '失败',
    canceled: '已取消',
  };

  function safeStatus(s) { return STATUS_LABEL[s] || s; }
  function safeFileStatus(s) { return FILE_STATUS_LABEL[s] || s; }

  function parseFormats(s) {
    try { return JSON.parse(s); } catch (e) { return []; }
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    return iso.replace('T', ' ').replace(/\+08:00$/, '');
  }

  function fmtDuration(startIso, endIso) {
    if (!startIso) return '—';
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    if (isNaN(start) || isNaN(end) || end < start) return '—';
    const s = Math.round((end - start) / 1000);
    if (s < 60) return s + ' 秒';
    if (s < 3600) return Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒';
    return Math.floor(s / 3600) + ' 时 ' + Math.floor((s % 3600) / 60) + ' 分';
  }

  function taskCard(t) {
    const card = document.createElement('div');
    card.className = 'task-card';

    const head = document.createElement('div');
    head.className = 'task-head';
    const id = document.createElement('span');
    id.className = 'task-id';
    id.textContent = '#' + t.id;
    const badge = document.createElement('span');
    badge.className = 'badge ' + t.status + (t.status === 'running' || t.status === 'uploading' ? ' pulsing' : '');
    badge.textContent = safeStatus(t.status);
    head.appendChild(id);
    head.appendChild(badge);
    card.appendChild(head);

    const meta = document.createElement('div');
    meta.className = 'task-meta';
    const fmts = parseFormats(t.output_formats);
    meta.textContent = [
      'tier: ' + (t.tier || '—'),
      '格式: ' + (fmts.length ? fmts.join(', ') : '—'),
      '创建: ' + fmtTime(t.created_at),
    ].join(' · ');
    card.appendChild(meta);

    const times = document.createElement('div');
    times.className = 'task-meta task-meta--times';
    times.textContent = [
      '开始: ' + fmtTime(t.started_at || t.created_at),
      '结束: ' + fmtTime(t.finished_at),
      '耗时: ' + fmtDuration(t.started_at || t.created_at, t.finished_at),
    ].join(' · ');
    card.appendChild(times);

    const total = t.total_files || 0;
    const done = t.completed_files || 0;
    const pct = total ? Math.round((done / total) * 100) : 0;
    const prog = document.createElement('div');
    prog.className = 'task-progress';
    const bar = document.createElement('span');
    bar.style.width = pct + '%';
    if (t.status === 'completed') bar.classList.add('done');
    prog.appendChild(bar);
    card.appendChild(prog);

    const files = t.files || [];
    if (files.length) {
      const fwrap = document.createElement('div');
      fwrap.className = 'task-files';
      files.forEach((f) => {
        const row = document.createElement('div');
        row.className = 'task-file';
        const fn = document.createElement('span');
        fn.className = 'fname';
        fn.textContent = f.file_name;
        fn.title = f.file_name;
        const fsz = document.createElement('span');
        fsz.className = 'fsize';
        fsz.textContent = (f.size != null) ? fmtSize(f.size) : '';
        const fs = document.createElement('span');
        fs.className = 'fstatus ' + (f.status || '');
        fs.textContent = safeFileStatus(f.status);
        row.appendChild(fn);
        row.appendChild(fsz);
        row.appendChild(fs);
        fwrap.appendChild(row);
      });
      card.appendChild(fwrap);
    }

    if (t.error) {
      const err = document.createElement('div');
      err.className = 'task-error';
      err.textContent = t.error;
      card.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'task-actions';
    if (t.status === 'completed' || t.status === 'partial') {
      const dl = document.createElement('button');
      dl.className = 'btn btn-download';
      dl.textContent = '下载全部';
      dl.addEventListener('click', () => downloadZip('/api/tasks/' + t.id + '/download', t.id + '.zip'));
      actions.appendChild(dl);
    }
    const del = document.createElement('button');
    del.className = 'btn btn-ghost';
    del.textContent = '删除';
    del.addEventListener('click', () => deleteTask(t.id));
    actions.appendChild(del);
    card.appendChild(actions);

    return card;
  }

  async function refreshTasks() {
    try {
      const tasks = await getJSON('/api/tasks');
      renderTasks(tasks);
    } catch (e) {
      // keep silent on transient poll errors; 401 already handled by request()
      if (state.token) toast('刷新任务失败：' + e.message, 'error');
    }
  }

  function renderTasks(tasks) {
    els.tasksList.innerHTML = '';
    if (!tasks || !tasks.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.innerHTML =
        '<div class="empty-glyph">∅</div><p>还没有任务</p>' +
        '<p class="hint">上传文件并开始转换后，任务会实时显示在这里</p>';
      els.tasksList.appendChild(empty);
      return;
    }
    tasks.forEach((t) => els.tasksList.appendChild(taskCard(t)));
  }

  async function downloadZip(url, filename) {
    try {
      const res = await request(url);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ('下载失败 (' + res.status + ')'));
      }
      const blob = await res.blob();
      const a = document.createElement('a');
      const objUrl = URL.createObjectURL(blob);
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objUrl), 1500);
    } catch (e) {
      toast('下载失败：' + e.message, 'error');
    }
  }

  async function deleteTask(id) {
    if (!confirm('确定删除任务 #' + id + ' 及其结果吗？')) return;
    try {
      const res = await request('/api/tasks/' + id, { method: 'DELETE' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ('删除失败 (' + res.status + ')'));
      }
      toast('任务已删除');
      await refreshTasks();
    } catch (e) {
      toast('删除失败：' + e.message, 'error');
    }
  }

  // ---- polling ----
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(refreshTasks, 3000);
  }
  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // ---- wiring ----
  function wire() {
    els.loginForm.addEventListener('submit', handleLogin);
    els.btnLogout.addEventListener('click', () => logout(true));
    els.btnTheme.addEventListener('click', toggleTheme);
    els.btnThemeLogin.addEventListener('click', toggleTheme);

    els.btnSettings.addEventListener('click', openModal);
    els.settingsModal.querySelectorAll('[data-close]').forEach((b) =>
      b.addEventListener('click', closeModal));
    els.btnTest.addEventListener('click', handleTestConfig);
    els.btnSaveConfig.addEventListener('click', handleSaveConfig);
    els.mineruStatus.addEventListener('click', checkMineruStatus);

    els.dropzone.addEventListener('click', () => els.fileInput.click());
    els.fileInput.addEventListener('change', () => {
      addFiles(els.fileInput.files);
      els.fileInput.value = '';
    });
    ['dragover', 'dragenter'].forEach((ev) =>
      els.dropzone.addEventListener(ev, (e) => {
        e.preventDefault();
        els.dropzone.classList.add('drag');
      }));
    ['dragleave', 'drop'].forEach((ev) =>
      els.dropzone.addEventListener(ev, (e) => {
        e.preventDefault();
        els.dropzone.classList.remove('drag');
      }));
    els.dropzone.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });

    els.tierSelect.querySelectorAll('.seg').forEach((b) =>
      b.addEventListener('click', () => setTier(b.dataset.tier)));
    els.formatSelect.querySelectorAll('.chip').forEach((b) =>
      b.addEventListener('click', () => setFormat(b.dataset.fmt)));

    els.btnSubmit.addEventListener('click', handleSubmit);
  }

  // ---- boot ----
  initTheme();
  loadVersion();
  wire();
  if (state.token && state.username) {
    els.currentUser.textContent = state.username;
    showApp();
    loadConfig().then(() => {
      refreshTasks();
      checkMineruStatus();
      startPolling();
    });
  } else {
    showLogin();
  }
})();
