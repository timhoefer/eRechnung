/* App confirmation, not proof of a human operator. No implicit approval. */
window.ChangeConfirmation = (() => {
  let queue = Promise.resolve();
  function ask(change) {
    const run = async () => {
      const dialog = document.getElementById("change-confirmation");
      const error = document.getElementById("change-cancel-error");
      const confirm = document.getElementById("change-confirm-button");
      error.hidden = true;
      confirm.disabled = false;
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
      for (;;) {
        const accepted = await new Promise(resolve => {
          dialog.returnValue = "cancel";
          dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once: true});
          dialog.showModal();
        });
        if (accepted && !confirm.disabled) return true;
        try {
          const response = await fetch(change.cancel_url, {
            method: "POST", body: new URLSearchParams({token: change.token}),
            headers: {"X-Requested-With": "fetch"},
          });
          if (!response.ok) throw new Error("Cancellation failed");
          return false;
        } catch (_) {
          // Keep this dialog's place in the queue until revocation succeeds.
          // Once cancellation was requested, only retrying it is allowed.
          error.hidden = false;
          confirm.disabled = true;
        }
      }
    };
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

// The full-page fallback uses a real POST even without JavaScript. With JS,
// revoke first. Restore export fields explicitly: history alone does not reliably
// retain dynamically filled customer and line-item controls across browsers.
const changeCancelForm = document.getElementById("change-cancel-form");
if (changeCancelForm) changeCancelForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  if (button?.disabled) return;
  if (button) button.disabled = true;
  const error = document.getElementById("change-cancel-error");
  error.hidden = true;
  try {
    const response = await fetch(changeCancelForm.action, {
      method: "POST", body: new FormData(changeCancelForm),
      headers: {"X-Requested-With": "fetch"},
    });
    if (!response.ok) throw new Error("Cancellation failed");
    if (changeCancelForm.dataset.draftKey) {
      const draft = {};
      for (const [key, value] of new FormData(document.getElementById("change-submit-form"))) {
        if (key !== "_change_confirmation") (draft[key] ||= []).push(value);
      }
      sessionStorage.setItem(changeCancelForm.dataset.draftKey, JSON.stringify(draft));
      window.location.assign(new FormData(changeCancelForm).get("back"));
    } else {
      history.back();
    }
  } catch (_) {
    error.hidden = false;
  } finally {
    if (button) button.disabled = false;
  }
});
