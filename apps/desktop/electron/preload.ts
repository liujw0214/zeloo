import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'

// Which translucency the OS can back. Asked synchronously because the renderer
// needs it before its first paint, and answered by main because deciding it
// needs `os.release()` — a sandboxed preload may only require electron, events,
// timers and url, so importing node:os here throws before contextBridge runs
// and takes the ENTIRE bridge down with it (window.ZELOODesktop undefined =>
// "Desktop IPC bridge is unavailable"). No reply means no glass, which degrades
// to an ordinary opaque window rather than a page thinned over nothing.
const translucencySupport = ipcRenderer.sendSync('Zeloo:translucency:support')
const hudWindowing = ipcRenderer.sendSync('Zeloo:hud:windowing')
const hudNativeDrag = hudWindowing?.nativeDrag === true
const launchFlags = ipcRenderer.sendSync('Zeloo:launch-flags')

contextBridge.exposeInMainWorld('ZELOODesktop', {
  glassSupported: translucencySupport?.glass === true,
  translucencySupported: translucencySupport?.translucency === true,
  // Launch-flag fact: the app was started with --local, so the renderer may
  // show the local-models surfaces. Static for the window's lifetime.
  localModelsEnabled: launchFlags?.localModels === true,
  // Launch-flag fact: the Nous free tier is on for this launch
  // (ZELOO_GUEST_ONBOARDING=1 or --guest-onboarding). Read-only; the same
  // decision is stamped onto every backend the app spawns.
  guestOnboardingEnabled: launchFlags?.guestOnboarding === true,
  getConnection: (profile, opts) => ipcRenderer.invoke('Zeloo:connection', profile, opts),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('Zeloo:connection:for', payload),
  getProfileRoutes: profiles => ipcRenderer.invoke('Zeloo:plugin-profile-routes', profiles),
  revalidateConnection: () => ipcRenderer.invoke('Zeloo:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('Zeloo:backend:touch', profile),
  getPoolLimits: () => ipcRenderer.invoke('Zeloo:pool-limits:get'),
  setPoolLimits: limits => ipcRenderer.invoke('Zeloo:pool-limits:set', limits),
  getGatewayWsUrl: profile => ipcRenderer.invoke('Zeloo:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('Zeloo:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('Zeloo:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('Zeloo:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('Zeloo:window:openInTerminal', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('Zeloo:window:openInstance'),
  openBrowserWindow: tabId => ipcRenderer.invoke('Zeloo:window:openBrowser', tabId),
  onBrowserPopoutClosed: callback => {
    const listener = (_event, tabId) => callback(tabId)
    ipcRenderer.on('Zeloo:browser-popout:closed', listener)

    return () => ipcRenderer.removeListener('Zeloo:browser-popout:closed', listener)
  },
  claimAmbientCue: key => ipcRenderer.invoke('Zeloo:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('Zeloo:wake-indicator:get'),
    setState: state => ipcRenderer.send('Zeloo:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('Zeloo:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('Zeloo:wake-indicator:state', listener)
    }
  },
  chatOnboarding: {
    grow: request => ipcRenderer.send('Zeloo:chat-onboarding:grow', request),
    soloBoot: () => ipcRenderer.send('Zeloo:chat-onboarding:solo-boot')
  },
  introReveal: {
    open: (payload?: { hideMain?: boolean }) => ipcRenderer.invoke('Zeloo:intro-reveal:open', payload),
    close: (payload?: { showMain?: boolean }) => ipcRenderer.invoke('Zeloo:intro-reveal:close', payload),
    skip: () => ipcRenderer.send('Zeloo:intro-reveal:skip'),
    ready: () => ipcRenderer.send('Zeloo:intro-reveal:ready'),
    onSkip: callback => {
      const listener = () => callback()

      ipcRenderer.on('Zeloo:intro-reveal:skip', listener)

      return () => ipcRenderer.removeListener('Zeloo:intro-reveal:skip', listener)
    },
    onClosed: callback => {
      const listener = () => callback()

      ipcRenderer.on('Zeloo:intro-reveal:closed', listener)

      return () => ipcRenderer.removeListener('Zeloo:intro-reveal:closed', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('Zeloo:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('Zeloo:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('Zeloo:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('Zeloo:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('Zeloo:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('Zeloo:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('Zeloo:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('Zeloo:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('Zeloo:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    nativeDrag: hudNativeDrag,
    windowing: {
      clientPlacement: hudWindowing?.clientPlacement !== false,
      controlDrag: hudWindowing?.controlDrag === true,
      nativeDrag: hudNativeDrag,
      solid: hudWindowing?.solid === true,
      workspaceTransfer: hudWindowing?.workspaceTransfer === true
    },
    open: request => ipcRenderer.invoke('Zeloo:hud:open', request),
    close: () => ipcRenderer.invoke('Zeloo:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('Zeloo:hud:ignore-mouse', ignore),
    beginMove: () => ipcRenderer.send('Zeloo:hud:begin-move'),
    endMove: () => ipcRenderer.send('Zeloo:hud:end-move'),
    moveBy: delta => ipcRenderer.send('Zeloo:hud:move-by', delta),
    setWorkspaceTransfer: transferring => ipcRenderer.send('Zeloo:hud:workspace-transfer', transferring),
    setBounds: bounds => ipcRenderer.send('Zeloo:hud:set-bounds', bounds),
    resetLayout: () => ipcRenderer.invoke('Zeloo:hud:reset-layout'),
    // Whether the band covers the window below the bar. Main pairs it with the
    // user's translucency setting to decide the native frost (macOS vibrancy /
    // Windows 11 DWM backdrop) — see hudFrostFor.
    setFrost: showing => ipcRenderer.invoke('Zeloo:hud:frost', showing),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('Zeloo:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('Zeloo:hud:goto', listener)

      return () => ipcRenderer.removeListener('Zeloo:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('Zeloo:hud:changed', listener)

      return () => ipcRenderer.removeListener('Zeloo:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('Zeloo:hud:cursor', listener)

      return () => ipcRenderer.removeListener('Zeloo:hud:cursor', listener)
    },
    // Main's game-overlay watch: whether a fullscreen app (a game) is under
    // the HUD, so the renderer can step back to the low-opacity overlay
    // treatment while one owns the screen.
    onGameOverlay: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('Zeloo:hud:game-overlay', listener)

      return () => ipcRenderer.removeListener('Zeloo:hud:game-overlay', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('Zeloo:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('Zeloo:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('Zeloo:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('Zeloo:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('Zeloo:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('Zeloo:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('Zeloo:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('Zeloo:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('Zeloo:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('Zeloo:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('Zeloo:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('Zeloo:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('Zeloo:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('Zeloo:connection-config:test', payload),
  // Opt-in OS-keychain encryption for stored gateway secrets (default off —
  // see secret-storage-policy.ts). get never touches the OS keychain.
  getSecretStorageEncryption: () => ipcRenderer.invoke('Zeloo:secret-storage:get'),
  setSecretStorageEncryption: (on: boolean) => ipcRenderer.invoke('Zeloo:secret-storage:set', on),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('Zeloo:connections:list'),
    save: payload => ipcRenderer.invoke('Zeloo:connections:save', payload),
    remove: id => ipcRenderer.invoke('Zeloo:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('Zeloo:connections:set-primary', id),
    setLaunchMode: mode => ipcRenderer.invoke('Zeloo:connections:set-launch-mode', mode),
    setLastUsed: id => ipcRenderer.invoke('Zeloo:connections:set-last-used', id),
    test: id => ipcRenderer.invoke('Zeloo:connections:test', id),
    updateManaged: id => ipcRenderer.invoke('Zeloo:connections:update-managed', id),
    // Fan out `Zeloo update` to every eligible registered connection.
    // Optional excludeIds skips rows the caller updates through another path.
    updateAll: options => ipcRenderer.invoke('Zeloo:connections:update-all', options),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:connections:changed', listener)

      return () => ipcRenderer.removeListener('Zeloo:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('Zeloo:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('Zeloo:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('Zeloo:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('Zeloo:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('Zeloo:connection-config:oauth-logout', remoteUrl),
  // Zeloo Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('Zeloo:cloud:status'),
    login: () => ipcRenderer.invoke('Zeloo:cloud:login'),
    logout: () => ipcRenderer.invoke('Zeloo:cloud:logout'),
    discover: org => ipcRenderer.invoke('Zeloo:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('Zeloo:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('Zeloo:profile:get'),
    remember: name => ipcRenderer.invoke('Zeloo:profile:remember', name),
    set: name => ipcRenderer.invoke('Zeloo:profile:set', name)
  },
  api: request => ipcRenderer.invoke('Zeloo:api', request),
  notify: payload => ipcRenderer.invoke('Zeloo:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('Zeloo:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('Zeloo:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('Zeloo:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('Zeloo:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('Zeloo:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('Zeloo:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('Zeloo:readFileText', filePath),
  readPluginSource: (filePath: string) => ipcRenderer.invoke('Zeloo:readPluginSource', filePath),
  selectPaths: options => ipcRenderer.invoke('Zeloo:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('Zeloo:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('Zeloo:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('Zeloo:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('Zeloo:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('Zeloo:saveImageFromUrl', url),
  contextMenuEdit: command => ipcRenderer.invoke('Zeloo:context-menu:edit', command),
  contextMenuCopyImage: () => ipcRenderer.invoke('Zeloo:context-menu:copy-image'),
  contextMenuSpellcheck: action => ipcRenderer.invoke('Zeloo:context-menu:spellcheck', action),
  contextMenuGuestAddWord: payload => ipcRenderer.invoke('Zeloo:context-menu:guest-add-word', payload),
  onContextMenuSpellcheck: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:context-menu-spellcheck', listener)

    return () => ipcRenderer.removeListener('Zeloo:context-menu-spellcheck', listener)
  },
  saveImageBuffer: (data, ext, name) => ipcRenderer.invoke('Zeloo:saveImageBuffer', { data, ext, name }),
  capturePreview: payload => ipcRenderer.invoke('Zeloo:capturePreview', payload),
  saveClipboardImage: () => ipcRenderer.invoke('Zeloo:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('Zeloo:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('Zeloo:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('Zeloo:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('Zeloo:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('Zeloo:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('Zeloo:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('Zeloo:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('Zeloo:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('Zeloo:keep-awake', on),
  setDisableF12: blocked => ipcRenderer.send('Zeloo:devtools:disable-f12', blocked),
  setPreviewShortcutActive: active => ipcRenderer.send('Zeloo:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('Zeloo:openExternal', url),
  mcpOauth: {
    // One-shot loopback listener for MCP OAuth against remote backends: bind
    // on this machine, hand redirectUri to mcp.servers.oauth.start, then wait
    // for the provider redirect and relay code/state via oauth.callback.
    listen: () => ipcRenderer.invoke('Zeloo:mcp-oauth:listen'),
    wait: (id, timeoutMs) => ipcRenderer.invoke('Zeloo:mcp-oauth:wait', id, timeoutMs),
    cancel: id => ipcRenderer.invoke('Zeloo:mcp-oauth:cancel', id)
  },
  openPreviewInBrowser: url => ipcRenderer.invoke('Zeloo:openPreviewInBrowser', url),
  reachPreviewUrl: url => ipcRenderer.invoke('Zeloo:preview:reach', url),
  setActiveConnectionRoute: route => ipcRenderer.send('Zeloo:connection:active-route', route),
  fetchLinkTitle: url => ipcRenderer.invoke('Zeloo:fetchLinkTitle', url),
  resolveFavicon: url => ipcRenderer.invoke('Zeloo:resolveFavicon', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('Zeloo:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('Zeloo:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('Zeloo:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('Zeloo:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('Zeloo:zoom:get'),
    // Synchronous zoom factor (1 = 100%). Coordinate math needs it in the
    // same tick as the event it converts, so no IPC round-trip here.
    factor: () => webFrame.getZoomFactor(),
    setPercent: percent => ipcRenderer.send('Zeloo:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:zoom:changed', listener)

      return () => ipcRenderer.removeListener('Zeloo:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('Zeloo:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('Zeloo:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('Zeloo:logs:renderer-error', report),
  readDir: dirPath => ipcRenderer.invoke('Zeloo:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('Zeloo:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('Zeloo:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('Zeloo:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('Zeloo:fs:desktopPluginsRoot'),
  reconcileDesktopPlugins: () => ipcRenderer.invoke('Zeloo:fs:reconcileDesktopPlugins'),
  logsRoot: () => ipcRenderer.invoke('Zeloo:fs:logsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('Zeloo:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('Zeloo:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('Zeloo:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('Zeloo:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('Zeloo:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('Zeloo:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('Zeloo:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('Zeloo:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('Zeloo:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('Zeloo:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('Zeloo:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('Zeloo:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('Zeloo:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('Zeloo:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('Zeloo:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('Zeloo:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('Zeloo:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('Zeloo:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('Zeloo:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('Zeloo:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('Zeloo:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('Zeloo:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('Zeloo:git:review:prList', repoPath, branches, numbers),
      fetchPrComment: (repoPath, url) => ipcRenderer.invoke('Zeloo:git:review:fetchPrComment', repoPath, url),
      createPr: repoPath => ipcRenderer.invoke('Zeloo:git:review:createPr', repoPath)
    }
  },
  terminal: {
    attach: id => ipcRenderer.invoke('Zeloo:terminal:attach', id),
    cwd: id => ipcRenderer.invoke('Zeloo:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('Zeloo:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('Zeloo:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('Zeloo:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('Zeloo:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `Zeloo:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `Zeloo:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('Zeloo:close-preview-requested', listener)
  },
  onPreviewNav: callback => {
    const listener = (_event, command) => callback(command)
    ipcRenderer.on('Zeloo:preview-nav', listener)

    return () => ipcRenderer.removeListener('Zeloo:preview-nav', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('Zeloo:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:open-updates', listener)

    return () => ipcRenderer.removeListener('Zeloo:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:deep-link', listener)

    return () => ipcRenderer.removeListener('Zeloo:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('Zeloo:deep-link-ready'),
  probePluginRepo: payload => ipcRenderer.invoke('Zeloo:plugin:probe', payload),
  installDesktopPlugin: payload => ipcRenderer.invoke('Zeloo:plugin:installDesktop', payload),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:window-state-changed', listener)

    return () => ipcRenderer.removeListener('Zeloo:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('Zeloo:focus-session', listener)

    return () => ipcRenderer.removeListener('Zeloo:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:notification-action', listener)

    return () => ipcRenderer.removeListener('Zeloo:notification-action', listener)
  },
  onNotificationActivate: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:notification-activate', listener)

    return () => ipcRenderer.removeListener('Zeloo:notification-activate', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('Zeloo:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:backend-exit', listener)

    return () => ipcRenderer.removeListener('Zeloo:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:connection:applied', listener)

    return () => ipcRenderer.removeListener('Zeloo:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:power-resume', listener)

    return () => ipcRenderer.removeListener('Zeloo:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('Zeloo:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('Zeloo:power-battery', listener)

    return () => ipcRenderer.removeListener('Zeloo:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:boot-progress', listener)

    return () => ipcRenderer.removeListener('Zeloo:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('Zeloo:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('Zeloo:bootstrap:continue-local'),
  recycleBackend: profile => ipcRenderer.invoke('Zeloo:backend:recycle', profile),
  resetBootstrap: () => ipcRenderer.invoke('Zeloo:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('Zeloo:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('Zeloo:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('Zeloo:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('Zeloo:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('Zeloo:version'),
  relaunchApp: () => ipcRenderer.invoke('Zeloo:app:relaunch'),
  getMachineProfile: () => ipcRenderer.invoke('Zeloo:machine:profile'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('Zeloo:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('Zeloo:uninstall:summary'),
    run: mode => ipcRenderer.invoke('Zeloo:uninstall:run', { mode })
  },
  updates: {
    check: opts => ipcRenderer.invoke('Zeloo:updates:check', opts),
    apply: opts => ipcRenderer.invoke('Zeloo:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('Zeloo:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('Zeloo:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('Zeloo:updates:progress', listener)

      return () => ipcRenderer.removeListener('Zeloo:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('Zeloo:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('Zeloo:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('Zeloo:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('Zeloo:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('Zeloo:found-in-page', listener)

    return () => ipcRenderer.removeListener('Zeloo:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('Zeloo:open-find-bar', listener)

    return () => ipcRenderer.removeListener('Zeloo:open-find-bar', listener)
  }
})
