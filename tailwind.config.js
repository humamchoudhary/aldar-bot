/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/*.html"],

  darkMode: "class",
  corePlugins: {
    preflight: false, // This disables Tailwind's global base/reset styles
  },
  theme: {
    extend: {},
  },
  plugins: [],
};
