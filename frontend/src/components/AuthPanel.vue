<script setup>
import { computed, ref, watch } from "vue";
import { ApiError, request } from "../api";
import AppIcon from "./AppIcon.vue";
import ErrorNotice from "./ErrorNotice.vue";

const props = defineProps({ mode: String, message: String });
const emit = defineEmits(["authenticated"]);
const registering = computed(() => props.mode === "register");
const username = ref("");
const password = ref("");
const confirmation = ref("");
const error = ref(null);
const busy = ref(false);
const showPassword = ref(false);

watch(() => props.mode, () => {
  error.value = null;
  password.value = "";
  confirmation.value = "";
  showPassword.value = false;
});

async function submit() {
  if (busy.value) return;
  const creating = registering.value;
  const name = username.value.trim();
  if (!/^[a-z0-9][a-z0-9_-]{2,31}$/i.test(name)) {
    error.value = new ApiError("用户名须为 3–32 个字母、数字、下划线或连字符，以字母或数字开头。");
    return;
  }
  if (creating && Array.from(password.value).length < 15) {
    error.value = new ApiError("密码至少需要 15 个字符。");
    return;
  }
  if (creating && confirmation.value !== password.value) {
    error.value = new ApiError("两次输入的密码不一致。");
    return;
  }
  error.value = null;
  busy.value = true;
  try {
    const account = await request(creating ? "/auth/register" : "/auth/login", {
      method: "POST",
      body: { username: name, password: password.value },
    });
    emit("authenticated", account, creating);
  } catch (cause) {
    error.value = cause;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="account-entry">
    <div class="brand account-brand">
      <span class="brand-symbol"><AppIcon name="cloud" size="25" /></span>
      <span>LLMCloud<small>模型微调工作台</small></span>
    </div>
    <section class="panel account-card" aria-labelledby="entry-title">
      <header class="account-card-title">
        <h1 id="entry-title">{{ registering ? "创建账号" : "登录工作台" }}</h1>
        <p v-if="message && !registering" role="status">{{ message }}</p>
      </header>
      <form class="account-form" @submit.prevent="submit">
        <ErrorNotice :error="error" />
        <label class="account-field">
          用户名
          <input v-model="username" name="username" autocomplete="username" required maxlength="32"
            :disabled="busy" placeholder="输入用户名" />
        </label>
        <div>
          <label class="account-field">
            密码
            <input v-model="password" name="password" :type="showPassword ? 'text' : 'password'"
              :autocomplete="registering ? 'new-password' : 'current-password'"
              required maxlength="256" :disabled="busy" placeholder="输入密码" />
          </label>
          <div class="account-password-tools">
            <small v-if="registering">至少 15 个字符</small>
            <button type="button" class="text-button" @click="showPassword = !showPassword">
              {{ showPassword ? "隐藏密码" : "显示密码" }}
            </button>
          </div>
        </div>
        <label v-if="registering" class="account-field">
          确认密码
          <input v-model="confirmation" name="confirmation" :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password" required maxlength="256" :disabled="busy" placeholder="再次输入密码" />
        </label>
        <button type="submit" class="button primary full-width" :disabled="busy">
          {{ busy ? (registering ? "正在注册…" : "正在登录…") : (registering ? "注册并登录" : "登录") }}
        </button>
      </form>
      <p class="account-switch">
        {{ registering ? "已有账号？" : "还没有账号？" }}
        <a class="text-button" :href="registering ? '#login' : '#register'" :aria-disabled="busy || undefined"
          @click="busy && $event.preventDefault()">{{ registering ? "返回登录" : "创建账号" }}</a>
      </p>
    </section>
  </main>
</template>
