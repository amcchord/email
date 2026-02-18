const { app, BrowserWindow, Menu, shell, ipcMain, safeStorage, session } = require('electron');
const path = require('path');
const fs = require('fs');

const isMac = process.platform === 'darwin';

// ── Config ──────────────────────────────────────────────────────────
const CONFIG_DIR = path.join(app.getPath('userData'));
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');

function readConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    }
  } catch {}
  return null;
}

function writeConfig(config) {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
}

// ── Windows ─────────────────────────────────────────────────────────
let mainWindow = null;
let loginWindow = null;

const SESSION_PARTITION = 'persist:mail';

function createMainWindow(serverUrl) {
  const ses = session.fromPartition(SESSION_PARTITION);

  const windowOptions = {
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#09090b',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      partition: SESSION_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  };

  if (isMac) {
    windowOptions.titleBarStyle = 'hiddenInset';
    windowOptions.trafficLightPosition = { x: 16, y: 18 };
  }

  mainWindow = new BrowserWindow(windowOptions);

  mainWindow.loadURL(serverUrl);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Handle new window requests (pop-out emails, compose, external links)
  const serverHost = new URL(serverUrl).host;

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.host === serverHost) {
        // Internal URL → open in a new app window with same session
        createChildWindow(url);
        return { action: 'deny' };
      }
    } catch {}
    // External URL → open in system browser
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Handle navigation to external sites (except OAuth)
  mainWindow.webContents.on('will-navigate', (event, url) => {
    try {
      const parsed = new URL(url);
      if (parsed.host === serverHost) return; // allow same-host navigation
      if (parsed.host === 'accounts.google.com' || parsed.host === 'oauth2.googleapis.com') return; // allow OAuth
      event.preventDefault();
      shell.openExternal(url);
    } catch {}
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createChildWindow(url) {
  const childOptions = {
    width: 800,
    height: 700,
    minWidth: 600,
    minHeight: 400,
    backgroundColor: '#09090b',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      partition: SESSION_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
    },
  };

  if (isMac) {
    childOptions.titleBarStyle = 'hiddenInset';
    childOptions.trafficLightPosition = { x: 16, y: 18 };
  }

  const child = new BrowserWindow(childOptions);

  child.loadURL(url);

  const config = readConfig();
  const serverHost = config ? new URL(config.serverUrl).host : null;

  child.webContents.setWindowOpenHandler(({ url: childUrl }) => {
    try {
      const parsed = new URL(childUrl);
      if (serverHost && parsed.host === serverHost) {
        createChildWindow(childUrl);
        return { action: 'deny' };
      }
    } catch {}
    shell.openExternal(childUrl);
    return { action: 'deny' };
  });

  child.webContents.on('will-navigate', (event, navUrl) => {
    try {
      const parsed = new URL(navUrl);
      if (serverHost && parsed.host === serverHost) return;
      if (parsed.host === 'accounts.google.com' || parsed.host === 'oauth2.googleapis.com') return;
      event.preventDefault();
      shell.openExternal(navUrl);
    } catch {}
  });
}

function createLoginWindow() {
  const loginOptions = {
    width: 480,
    height: 560,
    resizable: false,
    maximizable: false,
    backgroundColor: '#09090b',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  };

  if (isMac) {
    loginOptions.titleBarStyle = 'hiddenInset';
    loginOptions.trafficLightPosition = { x: 16, y: 18 };
  }

  loginWindow = new BrowserWindow(loginOptions);

  loginWindow.loadFile(path.join(__dirname, 'login.html'));

  loginWindow.once('ready-to-show', () => {
    loginWindow.show();
  });

  loginWindow.on('closed', () => {
    loginWindow = null;
  });
}

// ── IPC Handlers ────────────────────────────────────────────────────
ipcMain.handle('get-config', () => readConfig());

ipcMain.handle('save-config', (_event, config) => {
  writeConfig(config);
  return true;
});

ipcMain.handle('encrypt-credentials', (_event, creds) => {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Encryption not available');
  }
  const encrypted = safeStorage.encryptString(JSON.stringify(creds));
  return encrypted.toString('base64');
});

ipcMain.handle('decrypt-credentials', (_event, base64) => {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Encryption not available');
  }
  const buffer = Buffer.from(base64, 'base64');
  return JSON.parse(safeStorage.decryptString(buffer));
});

ipcMain.handle('try-auto-login', async () => {
  const config = readConfig();
  if (!config || !config.serverUrl) return { success: false, reason: 'no-config' };

  const ses = session.fromPartition(SESSION_PARTITION);

  if (config.authType === 'google') {
    // Check if session cookies are still valid
    try {
      const response = await ses.fetch(`${config.serverUrl}/api/auth/me`, {
        method: 'GET',
        credentials: 'include',
      });
      if (response.ok) {
        return { success: true, serverUrl: config.serverUrl };
      }
      return { success: false, reason: 'session-expired' };
    } catch {
      return { success: false, reason: 'network-error' };
    }
  }

  if (config.authType === 'password' && config.encryptedCredentials) {
    try {
      const buffer = Buffer.from(config.encryptedCredentials, 'base64');
      const creds = JSON.parse(safeStorage.decryptString(buffer));

      const response = await ses.fetch(`${config.serverUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: creds.username, password: creds.password }),
        credentials: 'include',
      });

      if (response.ok) {
        return { success: true, serverUrl: config.serverUrl };
      }
      return { success: false, reason: 'auth-failed' };
    } catch {
      return { success: false, reason: 'decrypt-failed' };
    }
  }

  return { success: false, reason: 'unknown-auth-type' };
});

ipcMain.handle('login', async (_event, serverUrl, username, password) => {
  const ses = session.fromPartition(SESSION_PARTITION);

  try {
    const response = await ses.fetch(`${serverUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'include',
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return { success: false, error: body.detail || 'Login failed' };
    }

    // Encrypt and store credentials
    let encryptedCredentials = null;
    if (safeStorage.isEncryptionAvailable()) {
      const encrypted = safeStorage.encryptString(JSON.stringify({ username, password }));
      encryptedCredentials = encrypted.toString('base64');
    }

    writeConfig({
      serverUrl,
      authType: 'password',
      encryptedCredentials,
    });

    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('login-with-google', async (_event, serverUrl) => {
  // Fetch the auth URL from the API (it returns JSON, not a redirect)
  const ses = session.fromPartition(SESSION_PARTITION);
  let authUrl;
  try {
    const response = await ses.fetch(`${serverUrl}/api/auth/google/login`, {
      method: 'GET',
      credentials: 'include',
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return { success: false, error: body.detail || 'Failed to start Google login' };
    }
    const data = await response.json();
    authUrl = data.auth_url;
    if (!authUrl) {
      return { success: false, error: 'No auth URL returned from server' };
    }
  } catch (err) {
    return { success: false, error: err.message };
  }

  return new Promise((resolve) => {
    const serverHost = new URL(serverUrl).host;

    const oauthWindow = new BrowserWindow({
      width: 600,
      height: 700,
      parent: loginWindow || undefined,
      modal: !!loginWindow,
      webPreferences: {
        partition: SESSION_PARTITION,
        contextIsolation: true,
        nodeIntegration: false,
      },
      show: false,
    });

    oauthWindow.once('ready-to-show', () => oauthWindow.show());

    oauthWindow.loadURL(authUrl);

    // Detect when OAuth flow redirects back to the server
    function checkOAuthComplete(url) {
      try {
        const parsed = new URL(url);
        if (parsed.host === serverHost && parsed.pathname === '/') {
          const loginError = parsed.searchParams.get('login_error');
          if (loginError) {
            oauthWindow.close();
            resolve({ success: false, error: loginError === 'not_allowed' ? 'That Google account is not on the allowed list' : 'Google login failed: ' + loginError });
            return;
          }
          // OAuth flow complete — server set auth cookies
          writeConfig({ serverUrl, authType: 'google' });
          oauthWindow.close();
          resolve({ success: true });
        }
      } catch {}
    }

    oauthWindow.webContents.on('will-navigate', (_ev, url) => checkOAuthComplete(url));
    oauthWindow.webContents.on('will-redirect', (_ev, url) => checkOAuthComplete(url));

    oauthWindow.on('closed', () => {
      resolve({ success: false, error: 'Window closed' });
    });
  });
});

ipcMain.handle('logout', async () => {
  const ses = session.fromPartition(SESSION_PARTITION);
  await ses.clearStorageData();
  try { fs.unlinkSync(CONFIG_PATH); } catch {}
  if (mainWindow) {
    mainWindow.close();
    mainWindow = null;
  }
  createLoginWindow();
  return true;
});

ipcMain.handle('load-main', (_event, serverUrl) => {
  if (loginWindow) {
    loginWindow.close();
    loginWindow = null;
  }
  createMainWindow(serverUrl);
});

// ── Menu ────────────────────────────────────────────────────────────
function doLogout() {
  const ses = session.fromPartition(SESSION_PARTITION);
  ses.clearStorageData().then(() => {
    try { fs.unlinkSync(CONFIG_PATH); } catch {}
    if (mainWindow) { mainWindow.close(); mainWindow = null; }
    createLoginWindow();
  });
}

function buildMenu() {
  const template = [];

  // macOS app menu (first item)
  if (isMac) {
    template.push({
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        {
          label: 'Log Out',
          click: doLogout,
        },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    });
  }

  // File menu (Windows/Linux get Log Out and Quit here)
  if (!isMac) {
    template.push({
      label: 'File',
      submenu: [
        {
          label: 'New Compose',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.executeJavaScript(
                "window.dispatchEvent(new CustomEvent('electron-navigate', { detail: { page: 'compose' } }))"
              );
              mainWindow.focus();
            }
          },
        },
        {
          label: 'Settings',
          accelerator: 'CmdOrCtrl+,',
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.executeJavaScript(
                "window.dispatchEvent(new CustomEvent('electron-navigate', { detail: { page: 'admin' } }))"
              );
              mainWindow.focus();
            }
          },
        },
        { type: 'separator' },
        {
          label: 'Log Out',
          click: doLogout,
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    });
  }

  template.push({
    label: 'Edit',
    submenu: [
      { role: 'undo' },
      { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      { role: 'selectAll' },
    ],
  });

  template.push({
    label: 'View',
    submenu: [
      { role: 'reload' },
      { role: 'forceReload' },
      { role: 'toggleDevTools' },
      { type: 'separator' },
      { role: 'resetZoom' },
      { role: 'zoomIn' },
      { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  });

  const windowSubmenu = [
    { role: 'minimize' },
    { role: 'zoom' },
    { role: 'close' },
  ];

  // On macOS, New Compose and Settings go in the Window menu
  if (isMac) {
    windowSubmenu.push(
      { type: 'separator' },
      {
        label: 'New Compose',
        accelerator: 'CmdOrCtrl+N',
        click: () => {
          if (mainWindow) {
            mainWindow.webContents.executeJavaScript(
              "window.dispatchEvent(new CustomEvent('electron-navigate', { detail: { page: 'compose' } }))"
            );
            mainWindow.focus();
          }
        },
      },
      {
        label: 'Settings',
        accelerator: 'CmdOrCtrl+,',
        click: () => {
          if (mainWindow) {
            mainWindow.webContents.executeJavaScript(
              "window.dispatchEvent(new CustomEvent('electron-navigate', { detail: { page: 'admin' } }))"
            );
            mainWindow.focus();
          }
        },
      },
    );
  }

  template.push({
    label: 'Window',
    submenu: windowSubmenu,
  });

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── App Lifecycle ───────────────────────────────────────────────────
app.whenReady().then(async () => {
  buildMenu();

  const config = readConfig();

  if (!config) {
    createLoginWindow();
    return;
  }

  // Try auto-login
  const ses = session.fromPartition(SESSION_PARTITION);

  if (config.authType === 'google') {
    try {
      const response = await ses.fetch(`${config.serverUrl}/api/auth/me`, {
        method: 'GET',
        credentials: 'include',
      });
      if (response.ok) {
        createMainWindow(config.serverUrl);
        return;
      }
    } catch {}
  } else if (config.authType === 'password' && config.encryptedCredentials) {
    try {
      const buffer = Buffer.from(config.encryptedCredentials, 'base64');
      const creds = JSON.parse(safeStorage.decryptString(buffer));
      const response = await ses.fetch(`${config.serverUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: creds.username, password: creds.password }),
        credentials: 'include',
      });
      if (response.ok) {
        createMainWindow(config.serverUrl);
        return;
      }
    } catch {}
  }

  // Auto-login failed
  createLoginWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const config = readConfig();
    if (config && config.serverUrl) {
      createMainWindow(config.serverUrl);
    } else {
      createLoginWindow();
    }
  }
});
