// Native dialog: keyboard focus stays inside; Escape closes; focus returns to
// the opener. Persist on the server because desktop launches use changing ports.
(function () {
  const dialog = document.getElementById("whats-new-dialog");
  if (!dialog) return;
  let saving = false;

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-whats-new]") && !dialog.open) dialog.showModal();
  });

  dialog.addEventListener("close", async () => {
    if (saving || dialog.dataset.seen === "true") return;
    saving = true;
    try {
      const response = await fetch(dialog.dataset.seenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: dialog.dataset.announcementId }),
      });
      if (response.ok) dialog.dataset.seen = "true";
    } catch (_) {
      // Closing must remain possible if saving fails. Show again next launch.
    } finally {
      saving = false;
    }
  });

  if (dialog.dataset.autoOpen === "true") dialog.showModal();
})();
