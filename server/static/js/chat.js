const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const charCount = document.getElementById("char-count");
const modelSelect = document.getElementById("model-select");

input.addEventListener("input", () => {
    charCount.textContent = input.value.length;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
});

input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event("submit"));
    }
});

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;

    addMessage("user", message);
    input.value = "";
    charCount.textContent = "0";
    input.style.height = "auto";
    sendBtn.disabled = true;

    const typingEl = document.createElement("div");
    typingEl.className = "typing-indicator";
    typingEl.textContent = "Thinking...";
    messagesEl.appendChild(typingEl);
    scrollToBottom();

    try {
        const resp = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                model: modelSelect.value,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            typingEl.remove();
            addMessage("blocked", err.detail || "Something went wrong.");
            sendBtn.disabled = false;
            return;
        }

        const contentType = resp.headers.get("content-type") || "";
        if (contentType.includes("text/event-stream")) {
            typingEl.remove();
            const assistantEl = addMessage("assistant", "");
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let fullText = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split("\n");
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const data = line.slice(6);
                    if (data === "[DONE]") continue;
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.replace) {
                            fullText = parsed.replace;
                            assistantEl.textContent = fullText;
                            assistantEl.className = "message message-blocked";
                        } else if (parsed.token) {
                            fullText += parsed.token;
                            assistantEl.textContent = fullText;
                        }
                    } catch {}
                }
                scrollToBottom();
            }
        } else {
            const data = await resp.json();
            typingEl.remove();
            if (data.blocked) {
                addMessage("blocked", data.response);
            } else {
                addMessage("assistant", data.response);
            }
        }
    } catch (err) {
        typingEl.remove();
        addMessage("blocked", "Connection error. Please try again.");
    }

    sendBtn.disabled = false;
    input.focus();
    updateCounter();
});

function addMessage(role, text) {
    const el = document.createElement("div");
    const classMap = {
        user: "message message-user",
        assistant: "message message-assistant",
        blocked: "message message-blocked",
    };
    el.className = classMap[role] || "message message-assistant";
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function updateCounter() {
    const counterEl = document.querySelector(".msg-counter");
    if (counterEl) {
        const parts = counterEl.textContent.split("/");
        if (parts.length === 2) {
            const current = parseInt(parts[0].trim()) + 1;
            counterEl.textContent = `${current} / ${parts[1].trim()}`;
        }
    }
}

// Load available models on page load
(async () => {
    try {
        const resp = await fetch("/api/models");
        if (resp.ok) {
            const data = await resp.json();
            const options = modelSelect.querySelectorAll("option");
            options.forEach((opt) => {
                if (!data.models.includes(opt.value)) {
                    opt.disabled = true;
                    opt.textContent += " (loading...)";
                }
            });
        }
    } catch {}
})();
