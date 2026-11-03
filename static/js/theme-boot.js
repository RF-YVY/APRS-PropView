(function () {
    try {
        var state = JSON.parse(localStorage.getItem('pvDesktopUIState') || '{}');
        var mode = state.uiMode || state.uiTheme || 'dark';
        var skin = state.uiSkin || 'standard';
        var accent = state.uiAccent || 'blue';
        var accentColors = {
            blue: '#58a6ff',
            cyan: '#39d5ff',
            green: '#3fb950',
            amber: '#d29922',
            purple: '#bc8cff',
            red: '#f85149'
        };
        if (mode === 'light') {
            document.documentElement.classList.add('ui-theme-light');
        }
        document.documentElement.dataset.uiMode = mode === 'light' ? 'light' : 'dark';
        document.documentElement.dataset.uiSkin = skin;
        document.documentElement.dataset.uiAccent = accent;
        document.documentElement.dataset.uiDensity = ['comfortable', 'compact', 'wallboard'].includes(state.uiDensity)
            ? state.uiDensity
            : 'compact';
        document.documentElement.style.setProperty(
            '--user-accent',
            accent === 'custom' && /^#[0-9a-f]{6}$/i.test(state.uiAccentCustom || '')
                ? state.uiAccentCustom
                : (accentColors[accent] || accentColors.blue)
        );
    } catch (e) {}
})();
