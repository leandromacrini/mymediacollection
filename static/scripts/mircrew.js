(() => {
  const form = document.getElementById("mircrew-import-form");
  const submit = document.getElementById("mircrew-import-submit");
  if (!form || !submit) return;

  form.addEventListener("submit", () => {
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Import...';
  });
})();
