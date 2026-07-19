/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#C2410C', hover: '#9A3412', light: '#FFF7ED' },
        accent: { DEFAULT: '#1D4ED8', light: '#EFF6FF' },
      },
      fontFamily: {
        heading: ['Inter', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '20px',
      },
      animation: {
        'fade-in': 'fade-in 0.5s ease forwards',
        'fade-in-scale': 'fade-in-scale 0.4s ease forwards',
        'float': 'float 3s ease-in-out infinite',
        'glow': 'pulse-glow 3s ease-in-out infinite',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
