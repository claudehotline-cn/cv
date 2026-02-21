import { ref } from 'vue'

const isDark = ref(false)

export function useTheme() {
    // Initialize theme
    const initTheme = () => {
        // 1. Check local storage
        const stored = localStorage.getItem('theme')

        if (stored) {
            isDark.value = stored === 'dark'
        } else {
            // 2. Check system preference
            // Force default to light for now as per requirement
            isDark.value = false
        }
        applyTheme()
    }

    // Toggle theme
    const toggleTheme = () => {
        isDark.value = !isDark.value
        applyTheme()
        localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    }

    // Apply theme to DOM
    const applyTheme = () => {
        const html = document.documentElement
        if (isDark.value) {
            html.classList.add('dark')
        } else {
            html.classList.remove('dark')
        }
    }

    return {
        isDark,
        initTheme,
        toggleTheme
    }
}
