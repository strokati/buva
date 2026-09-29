(() => {
  const params = new URLSearchParams(location.search);
  const box = document.getElementById("loginError");
  if (!box) return;
  if (params.get("error") === "rate") {
    box.textContent = "Забагато спроб входу. Зачекайте кілька хвилин і спробуйте знову.";
    box.hidden = false;
  } else if (params.get("error")) {
    box.textContent = "Невірне ім'я користувача або пароль.";
    box.hidden = false;
  }
  // clean the query string so refresh does not re-show the error
  if (params.get("error") && window.history.replaceState) {
    window.history.replaceState(null, "", location.pathname);
  }
})();
