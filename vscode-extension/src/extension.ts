import * as vscode from 'vscode';
import * as path from 'path';
import * as http from 'http';

// ---------------------------------------------------------------------------
// Configuration helpers
// ---------------------------------------------------------------------------

function getApiUrl(): string {
  const cfg = vscode.workspace.getConfiguration('myrag');
  return cfg.get<string>('apiUrl', 'http://127.0.0.1:8000');
}

function getProjectRoot(): string {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length > 0 ? folders[0].uri.fsPath : '';
}

// ---------------------------------------------------------------------------
// HTTP helpers (no external deps — uses built-in http module)
// ---------------------------------------------------------------------------

function httpPost(url: string, body: object): Promise<string> {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const parsed = new URL(url);
    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parseInt(parsed.port || '8000'),
      path: parsed.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
      },
    };
    const req = http.request(options, res => {
      let result = '';
      res.on('data', chunk => { result += chunk; });
      res.on('end', () => resolve(result));
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function httpGet(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let result = '';
      res.on('data', chunk => { result += chunk; });
      res.on('end', () => resolve(result));
    }).on('error', reject);
  });
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

let statusBar: vscode.StatusBarItem;

function updateStatus(text: string, tooltip?: string, color?: string) {
  statusBar.text = `🧠 ${text}`;
  statusBar.tooltip = tooltip || 'MyRAG — Local Code Intelligence';
  statusBar.color = color;
  statusBar.show();
}

async function pollHealth(base: string) {
  try {
    const res = await httpGet(`${base}/health`);
    const data = JSON.parse(res);
    updateStatus(`MyRAG v${data.version}`, 'MyRAG server is running');
    return true;
  } catch {
    updateStatus('Offline', 'MyRAG server not running. Start with: myrag serve', '#f87171');
    return false;
  }
}

// ---------------------------------------------------------------------------
// Webview panel (search UI)
// ---------------------------------------------------------------------------

let searchPanel: vscode.WebviewPanel | undefined;

function getSearchPanelHtml(base: string, projectRoot: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MyRAG Search</title>
  <style>
    :root {
      --bg: var(--vscode-editor-background);
      --fg: var(--vscode-editor-foreground);
      --input-bg: var(--vscode-input-background);
      --input-border: var(--vscode-input-border);
      --input-fg: var(--vscode-input-foreground);
      --btn-bg: var(--vscode-button-background);
      --btn-fg: var(--vscode-button-foreground);
      --btn-hover: var(--vscode-button-hoverBackground);
      --border: var(--vscode-panel-border);
      --accent: var(--vscode-focusBorder);
      --badge-bg: var(--vscode-badge-background);
      --badge-fg: var(--vscode-badge-foreground);
      --list-hover: var(--vscode-list-hoverBackground);
      --font: var(--vscode-font-family);
      --mono: var(--vscode-editor-font-family);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--fg);
      font-family: var(--font);
      font-size: 13px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      height: 100vh;
      overflow: hidden;
    }
    .search-row { display: flex; gap: 8px; align-items: flex-start; }
    textarea {
      flex: 1;
      background: var(--input-bg);
      color: var(--input-fg);
      border: 1px solid var(--input-border);
      border-radius: 4px;
      padding: 8px 10px;
      font-family: var(--font);
      font-size: 13px;
      resize: none;
      min-height: 60px;
      outline: none;
    }
    textarea:focus { border-color: var(--accent); }
    input[type=number] {
      width: 56px;
      background: var(--input-bg);
      color: var(--input-fg);
      border: 1px solid var(--input-border);
      border-radius: 4px;
      padding: 6px 8px;
      font-size: 12px;
      outline: none;
    }
    .btn {
      background: var(--btn-bg);
      color: var(--btn-fg);
      border: none;
      border-radius: 4px;
      padding: 8px 14px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
    }
    .btn:hover { background: var(--btn-hover); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-row { display: flex; gap: 6px; align-items: center; }
    label { font-size: 11px; color: var(--vscode-descriptionForeground); }
    .meta-row {
      display: flex; gap: 12px; align-items: center;
      font-size: 11px; color: var(--vscode-descriptionForeground);
      flex-wrap: wrap;
    }
    .badge {
      padding: 1px 7px;
      background: var(--badge-bg);
      color: var(--badge-fg);
      border-radius: 10px;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .results { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
    .result-card {
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }
    .card-header {
      display: flex; gap: 8px; align-items: center;
      padding: 8px 12px;
      background: var(--list-hover);
      font-size: 12px;
      flex-wrap: wrap;
    }
    .file-link {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      text-decoration: none;
      flex: 1;
    }
    .file-link:hover { text-decoration: underline; }
    .score { font-family: var(--mono); font-size: 10px; color: var(--vscode-descriptionForeground); }
    .code-block {
      font-family: var(--mono);
      font-size: 11.5px;
      line-height: 1.6;
      padding: 10px 14px;
      overflow-x: auto;
      white-space: pre;
      max-height: 200px;
      overflow-y: auto;
    }
    .spinner {
      display: inline-block; width: 12px; height: 12px;
      border: 2px solid var(--border); border-top-color: var(--accent);
      border-radius: 50%; animation: spin 0.7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .empty { text-align: center; padding: 40px; color: var(--vscode-descriptionForeground); }
    .error { padding: 10px; background: rgba(255,0,0,0.1); border-radius: 4px; font-size: 12px; }
    .sep { border: none; border-top: 1px solid var(--border); }
  </style>
</head>
<body>
  <div class="search-row">
    <textarea id="q" placeholder="Where is useAuth defined? | How does routing work? | What breaks if I change ThemeContext?" rows="3"></textarea>
    <div style="display:flex;flex-direction:column;gap:6px;">
      <div class="btn-row">
        <label>Top</label>
        <input type="number" id="topK" value="5" min="1" max="20" />
      </div>
      <button class="btn" id="searchBtn">Search</button>
    </div>
  </div>

  <div class="meta-row" id="metaRow" style="display:none">
    Intent: <span class="badge" id="intentBadge">—</span>
    <span id="confText"></span>
    <span style="margin-left:auto" id="elapsed"></span>
  </div>

  <hr class="sep" />

  <div class="results" id="results">
    <div class="empty">Search your codebase using natural language.<br/>
    <small>Ctrl+Enter to search</small></div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    const base = '${base}';
    const projectRoot = '${projectRoot.replace(/\\/g, '\\\\')}';

    function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    async function search() {
      const q = document.getElementById('q').value.trim();
      const topK = parseInt(document.getElementById('topK').value) || 5;
      if (!q) return;

      const btn = document.getElementById('searchBtn');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      document.getElementById('results').innerHTML = '<div class="empty"><span class="spinner" style="width:20px;height:20px;border-width:2px;"></span></div>';
      document.getElementById('metaRow').style.display = 'none';

      try {
        const res = await fetch(base + '/query', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({project_root: projectRoot, query: q, top_k: topK})
        });
        const data = await res.json();

        document.getElementById('metaRow').style.display = 'flex';
        document.getElementById('intentBadge').textContent = (data.intent||'').replace(/_/g,' ');
        document.getElementById('confText').textContent = 'conf: ' + Math.round((data.confidence||0)*100) + '%';
        document.getElementById('elapsed').textContent = data.elapsed_ms + ' ms';

        if (!data.results || !data.results.length) {
          document.getElementById('results').innerHTML = '<div class="empty">No results found. Try a different query or re-index.</div>';
          return;
        }

        document.getElementById('results').innerHTML = data.results.map((r, i) => \`
          <div class="result-card">
            <div class="card-header">
              <span style="font-weight:600;min-width:18px">#\${i+1}</span>
              <a class="file-link" onclick="openFile(\${JSON.stringify(r.file_path)}, \${r.start_line})">\${esc(r.file_path)}:\${r.start_line}</a>
              <span class="badge">\${esc(r.chunk_type)}</span>
              \${r.name ? '<span style="font-size:11px;opacity:0.8">'+esc(r.name)+'</span>' : ''}
              <span class="score">\${r.final_score.toFixed(3)}</span>
            </div>
            <pre class="code-block">\${esc(r.text)}</pre>
          </div>
        \`).join('');
      } catch(e) {
        document.getElementById('results').innerHTML = '<div class="error">Error: ' + esc(String(e)) + '</div>';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Search';
      }
    }

    function openFile(filePath, line) {
      vscode.postMessage({command: 'openFile', filePath, line});
    }

    document.getElementById('searchBtn').addEventListener('click', search);
    document.getElementById('q').addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); search(); }
    });
  </script>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function cmdSearch(context: vscode.ExtensionContext) {
  const base = getApiUrl();
  const projectRoot = getProjectRoot();

  if (!projectRoot) {
    vscode.window.showErrorMessage('MyRAG: Open a workspace folder first.');
    return;
  }

  if (searchPanel) {
    searchPanel.reveal(vscode.ViewColumn.Beside);
    return;
  }

  searchPanel = vscode.window.createWebviewPanel(
    'myragSearch',
    'MyRAG Search',
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
    }
  );

  searchPanel.webview.html = getSearchPanelHtml(base, projectRoot);

  // Handle messages from webview
  searchPanel.webview.onDidReceiveMessage(async msg => {
    if (msg.command === 'openFile') {
      const fullPath = path.isAbsolute(msg.filePath)
        ? msg.filePath
        : path.join(projectRoot, msg.filePath);
      try {
        const doc = await vscode.workspace.openTextDocument(fullPath);
        const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
        const line = Math.max(0, (msg.line || 1) - 1);
        const pos = new vscode.Position(line, 0);
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
      } catch {
        vscode.window.showWarningMessage(`MyRAG: Cannot open file: ${msg.filePath}`);
      }
    }
  });

  searchPanel.onDidDispose(() => { searchPanel = undefined; });
  context.subscriptions.push(searchPanel);
}

async function cmdIndex() {
  const base = getApiUrl();
  const projectRoot = getProjectRoot();

  if (!projectRoot) {
    vscode.window.showErrorMessage('MyRAG: Open a workspace folder first.');
    return;
  }

  const force = await vscode.window.showQuickPick(
    ['Incremental (index changed files only)', 'Force re-index (index all files)'],
    { placeHolder: 'Choose indexing mode' }
  );
  if (!force) { return; }
  const forceReindex = force.includes('Force');

  updateStatus('Indexing…', 'Indexing project…');
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'MyRAG: Indexing project…',
      cancellable: false,
    },
    async progress => {
      progress.report({ increment: 0, message: projectRoot });
      try {
        const res = await httpPost(`${base}/index`, {
          project_root: projectRoot,
          force_reindex: forceReindex,
        });
        const data = JSON.parse(res);
        const s = data.stats;
        progress.report({ increment: 100 });
        vscode.window.showInformationMessage(
          `MyRAG: Indexed ${s.files_indexed} files, ${s.chunks_indexed} chunks in ${s.elapsed_ms}ms`
        );
        updateStatus('Ready', `Last indexed: ${projectRoot}`);
      } catch (e) {
        vscode.window.showErrorMessage(`MyRAG: Indexing failed — ${e}`);
        updateStatus('Error', String(e), '#f87171');
      }
    }
  );
}

async function cmdOpenUI() {
  const base = getApiUrl();
  vscode.env.openExternal(vscode.Uri.parse(base));
}

async function cmdQuerySelection() {
  const base = getApiUrl();
  const projectRoot = getProjectRoot();
  const editor = vscode.window.activeTextEditor;

  if (!editor || !projectRoot) { return; }

  const selection = editor.document.getText(editor.selection).trim();
  if (!selection) {
    vscode.window.showWarningMessage('MyRAG: Select some text first.');
    return;
  }

  const query = `Where is ${selection} defined? How does it work?`;
  updateStatus('Searching…');

  try {
    const res = await httpPost(`${base}/query`, {
      project_root: projectRoot,
      query,
      top_k: 5,
    });
    const data = JSON.parse(res);

    if (!data.results || !data.results.length) {
      vscode.window.showInformationMessage('MyRAG: No results found.');
      return;
    }

    // Show quick pick with results
    const items = data.results.map((r: any, i: number) => ({
      label: `$(symbol-function) ${r.name || r.chunk_type} — ${r.file_path}:${r.start_line}`,
      description: `score: ${r.final_score.toFixed(3)}`,
      detail: r.text.slice(0, 120).replace(/\n/g, ' '),
      result: r,
    }));

    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: `Results for: ${query}`,
      matchOnDetail: true,
    });

    if (picked) {
      const fullPath = path.isAbsolute(picked.result.file_path)
        ? picked.result.file_path
        : path.join(projectRoot, picked.result.file_path);
      try {
        const doc = await vscode.workspace.openTextDocument(fullPath);
        const ed = await vscode.window.showTextDocument(doc);
        const line = Math.max(0, picked.result.start_line - 1);
        const pos = new vscode.Position(line, 0);
        ed.selection = new vscode.Selection(pos, pos);
        ed.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
      } catch {
        vscode.window.showWarningMessage(`Cannot open: ${picked.result.file_path}`);
      }
    }

    updateStatus('Ready');
  } catch (e) {
    vscode.window.showErrorMessage(`MyRAG: Query failed — ${e}`);
    updateStatus('Error', String(e), '#f87171');
  }
}

// ---------------------------------------------------------------------------
// Activation / deactivation
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext) {
  // Status bar
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = 'myrag.search';
  context.subscriptions.push(statusBar);
  updateStatus('MyRAG');

  // Poll server health
  const base = getApiUrl();
  pollHealth(base);
  const healthTimer = setInterval(() => pollHealth(base), 30000);
  context.subscriptions.push({ dispose: () => clearInterval(healthTimer) });

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('myrag.search', () => cmdSearch(context)),
    vscode.commands.registerCommand('myrag.index', cmdIndex),
    vscode.commands.registerCommand('myrag.openUI', cmdOpenUI),
    vscode.commands.registerCommand('myrag.querySelection', cmdQuerySelection),
  );

  // Re-index on file save (if auto-index enabled in config)
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async doc => {
      const cfg = vscode.workspace.getConfiguration('myrag');
      if (!cfg.get<boolean>('autoIndex', false)) { return; }
      const ext = path.extname(doc.fileName);
      if (!['.js', '.jsx', '.ts', '.tsx'].includes(ext)) { return; }
      const projectRoot = getProjectRoot();
      if (!projectRoot) { return; }
      try {
        await httpPost(`${base}/index`, {project_root: projectRoot, force_reindex: false});
      } catch { /* silent on auto-index */ }
    })
  );
}

export function deactivate() {
  if (searchPanel) { searchPanel.dispose(); }
}
