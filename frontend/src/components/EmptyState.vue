<script setup>
import AppIcon from "./AppIcon.vue";
defineProps({
  icon: { type: String, default: "data" },
  title: String,
  description: String,
});
</script>
<template>
  <div class="empty-state">
    <span class="empty-icon"><AppIcon :name="icon" size="28" /></span>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>
