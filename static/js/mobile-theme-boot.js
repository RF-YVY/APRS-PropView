(function applySavedMobileTheme() {
    try {
        var state = JSON.parse(localStorage.getItem('pvDesktopUIState') || '{}');
        var allowedSkins = ['standard', 'mission-control', 'industrial', 'neon-grid', 'terminal-green', 'radio', 'iview', 'hackr'];
        var accentColors = {
            blue: '#58a6ff', cyan: '#39d5ff', green: '#3fb950',
            amber: '#d29922', purple: '#bc8cff', red: '#f85149'
        };
        var mode = state.uiMode || state.uiTheme || 'dark';
        var skin = allowedSkins.indexOf(state.uiSkin) >= 0 ? state.uiSkin : 'standard';
        var accent = state.uiAccent || 'blue';
        var accentColor = accent === 'custom'
            ? (state.uiAccentCustom || '#58a6ff')
            : (accentColors[accent] || accentColors.blue);
        var root = document.documentElement;
        root.dataset.uiMode = mode === 'light' ? 'light' : 'dark';
        root.dataset.uiSkin = skin;
        root.dataset.uiAccent = accent;
        root.classList.toggle('ui-light', mode === 'light');
        root.style.setProperty('--user-accent', accentColor);
    } catch (_) {
        document.documentElement.dataset.uiMode = 'dark';
        document.documentElement.dataset.uiSkin = 'standard';
    }
})();
