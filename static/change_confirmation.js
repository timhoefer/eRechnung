/* App confirmation, not proof of a human operator. No implicit approval. */
window.ChangeConfirmation = (() => {
  let queue = Promise.resolve();
  function ask(change) {
    const run = () => new Promise(resolve => {
      const dialog = document.getElementById("change-confirmation");
      document.getElementById("change-title").textContent = change.title;
      document.getElementById("change-message").textContent = change.message;
      const rows = document.getElementById("change-rows");
      rows.replaceChildren();
      for (const detail of change.details) {
        const row = document.createElement("tr");
        for (const key of ["label", "before", "after"]) {
          const cell = document.createElement(key === "label" ? "th" : "td");
          cell.textContent = detail[key];
          row.appendChild(cell);
        }
        rows.appendChild(row);
      }
      dialog.returnValue = "cancel";
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once: true});
      dialog.showModal();
    });
    const answer = queue.then(run);
    queue = answer.catch(() => {});
    return answer;
  }

  async function confirmedFetch(url, options = {}, interactive = true) {
    const headers = new Headers(options.headers);
    headers.set("X-Requested-With", "fetch");
    let response = await fetch(url, {...options, headers});
    while (response.status === 428 && interactive) {
      const data = await response.json();
      if (!data.confirmation || !await ask(data.confirmation)) {
        if (data.confirmation) {
          await fetch(data.confirmation.cancel_url, {
            method: "POST", body: new URLSearchParams({token: data.confirmation.token}),
          }).catch(() => {});
        }
        const error = new Error("Change cancelled");
        error.name = "AbortError";
        throw error;
      }
      headers.set("X-Change-Confirmation", data.confirmation.token);
      // Retry the captured request, never reread a form edited behind the dialog.
      response = await fetch(url, {...options, headers});
    }
    return response;
  }
  return {fetch: confirmedFetch};
})();
