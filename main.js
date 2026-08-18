const { app, BrowserWindow, Menu, ipcMain, shell } = require('electron');
const path = require('node:path');

function packagedPaperPath() {
  const paper = path.join(app.getAppPath(), 'output', 'pdf', 'lanterntrace-frontier-forecasting.pdf');
  return paper.replace(`${path.sep}app.asar${path.sep}`, `${path.sep}app.asar.unpacked${path.sep}`);
}

ipcMain.handle('open-paper', () => shell.openPath(packagedPaperPath()));

function createWindow() {
  const window = new BrowserWindow({
    width: 1430,
    height: 930,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: '#071326',
    title: 'LanternTrace Explorer',
    titleBarStyle: 'hidden',
    trafficLightPosition: { x: 18, y: 17 },
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  window.setMenuBarVisibility(false);
  // Keep the reference-style window visible on the primary desktop even when
  // another display has a negative origin.
  window.setPosition(40, 12);
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) shell.openExternal(url);
    if (url.startsWith('file://')) {
      const requested = decodeURIComponent(new URL(url).pathname);
      const paper = path.join(app.getAppPath(), 'output', 'pdf', 'lanterntrace-frontier-forecasting.pdf');
      if (path.normalize(requested) === path.normalize(paper)) {
        shell.openPath(packagedPaperPath());
      }
    }
    return { action: 'deny' };
  });
  // Keep the desktop shell on the same current build as the public explorer.
  // The bundled page remains an offline fallback.
  window.loadURL('https://www.alex-dils.com/lanterntrace/app/?v=20260817-host-vegetation');
  window.webContents.once('did-fail-load', () => window.loadFile('index.html'));
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
