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
                        if (parsed.auto_model) {
                            // Show which model was auto-selected
                            showAutoModelBadge(assistantEl, parsed.auto_model, parsed.category);
                        } else if (parsed.replace) {
                            fullText = parsed.replace;
                            setMessageText(assistantEl, fullText);
                            assistantEl.className = "message message-blocked";
                        } else if (parsed.token) {
                            fullText += parsed.token;
                            setMessageText(assistantEl, fullText);
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

function addMessage(role, text, meta) {
    const el = document.createElement("div");
    const classMap = {
        user: "message message-user",
        assistant: "message message-assistant",
        blocked: "message message-blocked",
    };
    el.className = classMap[role] || "message message-assistant";

    const contentSpan = document.createElement("span");
    contentSpan.className = "message-content";
    contentSpan.textContent = text;
    el.appendChild(contentSpan);

    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
}

function setMessageText(el, text) {
    const contentSpan = el.querySelector(".message-content");
    if (contentSpan) {
        contentSpan.textContent = text;
    } else {
        el.textContent = text;
    }
}

function showAutoModelBadge(el, model, category) {
    const categoryLabels = {
        reasoning: "Math & Logic",
        creative: "Creative",
        general: "General Knowledge",
    };
    const badge = document.createElement("div");
    badge.className = "auto-model-badge";
    badge.textContent = `${categoryLabels[category] || category} → ${model}`;
    el.insertBefore(badge, el.firstChild);
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

// --- Load conversation history (last 7 days) ---
async function loadHistory() {
    try {
        const resp = await fetch("/api/history?days=7");
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.messages || data.messages.length === 0) return;

        // Remove welcome message when there's history
        const welcome = messagesEl.querySelector(".welcome-message");
        if (welcome) welcome.remove();

        // Group messages by date
        let lastDate = "";
        for (const msg of data.messages) {
            const msgDate = msg.timestamp ? msg.timestamp.split(" ")[0] : "";
            if (msgDate && msgDate !== lastDate) {
                addDateSeparator(msgDate);
                lastDate = msgDate;
            }
            addMessage(msg.role, msg.content);
        }

        scrollToBottom();
    } catch {}
}

function addDateSeparator(dateStr) {
    const el = document.createElement("div");
    el.className = "date-separator";

    const today = new Date().toISOString().split("T")[0];
    const yesterday = new Date(Date.now() - 86400000).toISOString().split("T")[0];

    let label = dateStr;
    if (dateStr === today) label = "Today";
    else if (dateStr === yesterday) label = "Yesterday";
    else {
        const d = new Date(dateStr + "T00:00:00");
        label = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    }

    el.innerHTML = `<span>${label}</span>`;
    messagesEl.appendChild(el);
}

// Load available models on page load
(async () => {
    try {
        const resp = await fetch("/api/models");
        if (resp.ok) {
            const data = await resp.json();
            const options = modelSelect.querySelectorAll("option");
            options.forEach((opt) => {
                if (opt.value === "auto") return; // skip auto option
                if (!data.models.includes(opt.value)) {
                    opt.disabled = true;
                    opt.textContent += " (loading...)";
                }
            });
        }
    } catch {}

    // Load conversation history after models
    await loadHistory();
})();
