/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#02050b',
        midnight: '#050a14',
        surface: 'rgba(10, 17, 27, 0.76)',
        'surface-2': 'rgba(14, 23, 35, 0.9)',
        'surface-3': 'rgba(255, 255, 255, 0.055)',
        border: 'rgba(228, 219, 201, 0.09)',
        'border-2': 'rgba(125, 231, 255, 0.18)',
        accent: '#7de7ff',
        'accent-2': '#c7ab66',
        txt: '#e4dbc9',
        'txt-soft': '#cfc4b3',
        muted: '#8e958f',
        steel: '#6e7d88',
        good: '#74d394',
        bad: '#ef6b77',
        warn: '#d6b65a',
      },
      fontFamily: {
        sans: ['Syne', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['Cormorant', 'ui-serif', 'Georgia', 'serif'],
        mono: ['DM Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        none: '0px',
        sm: '4px',
        DEFAULT: '6px',
        md: '8px',
        lg: '8px',
        xl: '8px',
        '2xl': '8px',
      },
      boxShadow: {
        card: '0 24px 90px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.05)',
        'card-hover': '0 30px 110px rgba(0,0,0,0.5), 0 0 36px rgba(125,231,255,0.08)',
        glow: '0 0 24px rgba(125,231,255,0.12), 0 0 80px rgba(0,208,232,0.06)',
      },
      transitionTimingFunction: {
        observatory: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      spacing: {
        18: '4.5rem',
        22: '5.5rem',
      },
    },
  },
  plugins: [],
}
