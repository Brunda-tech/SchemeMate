(() => {
    const launcher = document.getElementById("chatbot-launcher");
    const panel = document.getElementById("chatbot-panel");
    const closeButton = document.getElementById("chatbot-close");
    const form = document.getElementById("chatbot-form");
    const input = document.getElementById("chatbot-input");
    const sendButton = document.getElementById("chatbot-send");
    const messagesElement = document.getElementById("chatbot-messages");
    const faqButtons = document.querySelectorAll(".chatbot-faqs button");

    if (!launcher || !panel || !closeButton || !form || !input || !sendButton || !messagesElement) {
        return;
    }

    const conversation = [];

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", String(open));
        if (open) {
            input.focus();
        }
    }

    function addMessage(content, role, sources = [], mode = "") {
        const message = document.createElement("div");
        message.className = `chatbot-message chatbot-message-${role}`;
        message.textContent = content;
        messagesElement.appendChild(message);

        if (mode) {
            const modeLabel = document.createElement("div");
            modeLabel.className = "chatbot-mode";
            if (mode === "gemini") {
                modeLabel.textContent = "AI-assisted · based on SchemeMate scheme records";
            } else if (mode === "faq") {
                modeLabel.textContent = "SchemeMate website FAQ · offline help";
            } else {
                modeLabel.textContent = "SchemeMate database suggestions · AI key not configured";
            }
            messagesElement.appendChild(modeLabel);
        }

        if (sources.length) {
            const sourceList = document.createElement("div");
            sourceList.className = "chatbot-sources";
            const label = document.createElement("strong");
            label.textContent = "Official sources";
            sourceList.appendChild(label);

            sources.forEach((source) => {
                if (!source || typeof source.name !== "string" || typeof source.url !== "string") {
                    return;
                }
                let parsedUrl;
                try {
                    parsedUrl = new URL(source.url);
                } catch {
                    return;
                }
                if (parsedUrl.protocol !== "https:") {
                    return;
                }
                const link = document.createElement("a");
                link.href = parsedUrl.href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = source.name;
                sourceList.appendChild(link);
            });
            if (sourceList.querySelector("a")) {
                messagesElement.appendChild(sourceList);
            }
        }
        messagesElement.scrollTop = messagesElement.scrollHeight;
    }

    launcher.addEventListener("click", () => setOpen(panel.hidden));
    closeButton.addEventListener("click", () => setOpen(false));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || sendButton.disabled) {
            return;
        }

        conversation.push({ role: "user", content: text });
        addMessage(text, "user");
        input.value = "";
        sendButton.disabled = true;
        sendButton.textContent = "…";

        const pending = document.createElement("div");
        pending.className = "chatbot-message chatbot-message-assistant chatbot-pending";
        pending.textContent = "Checking SchemeMate’s scheme information…";
        messagesElement.appendChild(pending);
        messagesElement.scrollTop = messagesElement.scrollHeight;

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: conversation.slice(-8) }),
            });
            const result = await response.json();
            pending.remove();
            if (!response.ok) {
                addMessage(result.error || "The assistant couldn’t answer. Please try again.", "assistant");
                return;
            }

            conversation.push({ role: "assistant", content: result.reply });
            addMessage(result.reply, "assistant", result.sources, result.mode);
        } catch {
            pending.remove();
            addMessage("Couldn’t connect to the assistant. Check your connection and try again.", "assistant");
        } finally {
            sendButton.disabled = false;
            sendButton.textContent = "Send";
            input.focus();
        }
    });

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    faqButtons.forEach((button) => {
        button.addEventListener("click", () => {
            input.value = button.textContent.trim();
            form.requestSubmit();
        });
    });
})();
