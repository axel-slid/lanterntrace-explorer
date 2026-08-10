const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lanternTrace', {
  appName: 'LanternTrace Explorer',
  version: '0.2.0',
  openPaper: () => ipcRenderer.invoke('open-paper')
});
