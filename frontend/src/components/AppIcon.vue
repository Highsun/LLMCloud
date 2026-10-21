<script setup>
defineProps({ name: String, size: { type: [String, Number], default: 20 } });
const paths = {
  cloud:
    "M7 18a5 5 0 0 1-.8-9.93A6 6 0 0 1 18 7a5.5 5.5 0 0 1 0 11H7Z M9 12l3-3 3 3 M12 9v8",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  data: "M20 6c0 2.2-3.6 4-8 4S4 8.2 4 6s3.6-4 8-4 8 1.8 8 4Z M4 6v12c0 2.2 3.6 4 8 4s8-1.8 8-4V6 M4 12c0 2.2 3.6 4 8 4s8-1.8 8-4",
  sliders: "M4 7h16 M4 17h16 M8 3v8 M16 13v8",
  activity: "M2 12h5l3-9 4 18 3-9h5",
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 2V11.5A8.5 8.5 0 0 1 9.5 3h3a8.5 8.5 0 0 1 8.5 8.5Z M7 10h10 M7 14h6",
  book: "M12 5v16 M12 5C8 2 4 3 2 4v15c3-1 6-1 10 2 4-3 7-3 10-2V4c-2-1-6-2-10 1Z",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  upload: "M12 16V3 M7 8l5-5 5 5 M3 15v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5",
  download: "M12 3v13 M7 11l5 5 5-5 M3 17v4h18v-4",
  refresh: "M20 7a9 9 0 1 0 1 9 M20 2v5h-5",
  plus: "M12 5v14 M5 12h14",
  file: "M14 2H5v20h14V7l-5-5Z M14 2v6h5 M8 13h8 M8 17h5",
  chevron: "m9 5 7 7-7 7",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12 M6 18 18 6",
  info: "M12 8h.01 M12 11v6 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  chip: "M6 6h12v12H6z M9 9h6v6H9z M9 2v4 M15 2v4 M9 18v4 M15 18v4 M2 9h4 M2 15h4 M18 9h4 M18 15h4",
  clock: "M12 6v6l4 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  terminal: "m4 6 6 6-6 6 M12 18h8",
  external: "M14 3h7v7 M10 14 21 3 M10 3H3v18h18v-7",
  menu: "M3 6h18 M3 12h18 M3 18h18",
  layers: "m12 2 10 5-10 5L2 7l10-5Z M2 12l10 5 10-5 M2 17l10 5 10-5",
};
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.65"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.grid" />
  </svg>
</template>
