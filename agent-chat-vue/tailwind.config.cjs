/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Use CSS variables so sections can override palette locally.
        primary: 'rgb(var(--twc-primary) / <alpha-value>)',
        'background-light': 'rgb(var(--twc-background-light) / <alpha-value>)',
        'background-dark': 'rgb(var(--twc-background-dark) / <alpha-value>)',
        'surface-light': 'rgb(var(--twc-surface-light) / <alpha-value>)',
        'surface-dark': 'rgb(var(--twc-surface-dark) / <alpha-value>)',
        'text-main': 'rgb(var(--twc-text-main) / <alpha-value>)',
        'text-secondary': 'rgb(var(--twc-text-secondary) / <alpha-value>)',
        'border-color': 'rgb(var(--twc-border-color) / <alpha-value>)',
      },
      fontFamily: {
        display: ['Manrope', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '0.25rem',
        lg: '0.5rem',
        xl: '0.75rem',
        '2xl': '1rem',
        full: '9999px',
      },
      boxShadow: {
        card: '0px 2px 8px rgba(0, 0, 0, 0.04), 0px 1px 2px rgba(0, 0, 0, 0.02)',
      },
    },
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')],
}
