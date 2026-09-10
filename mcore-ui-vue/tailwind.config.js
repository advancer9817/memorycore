/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#121214',
        card: '#18181b',
        border: '#27272a',
        primary: '#6366f1',
        accent: '#da7756',
        muted: '#71717a'
      }
    },
  },
  plugins: [],
}
