if (theme === 'system') {
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        root.classList.add('dark');
    } else {
        root.classList.remove('dark');
    }
} else if (theme === 'dark') {
    root.classList.add('dark');
} else {
    root.classList.remove('dark');
}
// Listen for system theme changes if 'system' is selected
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'system') {
        window.applyTheme('system');
    }
});
