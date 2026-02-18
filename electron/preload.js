const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  platform: process.platform,

  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (config) => ipcRenderer.invoke('save-config', config),

  encryptCredentials: (creds) => ipcRenderer.invoke('encrypt-credentials', creds),
  tryAutoLogin: () => ipcRenderer.invoke('try-auto-login'),

  login: (serverUrl, username, password) => ipcRenderer.invoke('login', serverUrl, username, password),
  loginWithGoogle: (serverUrl) => ipcRenderer.invoke('login-with-google', serverUrl),

  logout: () => ipcRenderer.invoke('logout'),
  loadMain: (serverUrl) => ipcRenderer.invoke('load-main', serverUrl),
});
