(function () {
  const keyField = document.getElementById("companion-key");
  const copyKey = document.getElementById("companion-copy");
  const rotateKey = document.getElementById("companion-rotate");
  if (!keyField || !copyKey || !rotateKey) return;

  copyKey.addEventListener("click", async () => {
    const value = keyField.value;
    try {
      await navigator.clipboard.writeText(value);
    } catch (error) {
      keyField.focus();
      keyField.select();
      document.execCommand("copy");
    }
    Ik.toast("Key copied");
  });

  rotateKey.addEventListener("click", () => {
    const slug = window.location.pathname.split("/").filter(Boolean)[0];
    Ik.confirm({
      title: "New companion key",
      body: "<p>The program keeps the old key until you paste this new one.</p>",
      confirmLabel: "Make a new key",
      tone: "accent",
      onConfirm() {
        const form = document.createElement("form");
        form.method = "post";
        form.action = `/api/${slug}/attendance/token`;
        document.body.appendChild(form);
        form.submit();
        return false;
      },
    });
  });
})();
