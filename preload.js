const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lanternTrace', {
  appName: 'LanternTrace Explorer',
  version: '0.3.1',
  openPaper: () => ipcRenderer.invoke('open-paper')
});
