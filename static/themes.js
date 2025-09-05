window.applyTheme = (theme) => {
const root = document.documentElement;
localStorage.setItem('theme', theme);

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

};

// Initial load: Apply the saved theme from local storage or default
document.addEventListener('DOMContentLoaded', () => {
const savedTheme = localStorage.getItem('theme') || 'light';
window.applyTheme(savedTheme);

// Listen for system theme changes if 'system' is selected
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'system') {
        window.applyTheme('system');
    }
});

});
