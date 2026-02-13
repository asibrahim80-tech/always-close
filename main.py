import os
from openai import OpenAI
from flask import Flask, request, jsonify, render_template_string

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user

app = Flask(__name__)

AI_INTEGRATIONS_OPENAI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

# This is using Replit's AI Integrations service, which provides OpenAI-compatible API access without requiring your own OpenAI API key.
client = OpenAI(
    api_key=AI_INTEGRATIONS_OPENAI_API_KEY,
    base_url=AI_INTEGRATIONS_OPENAI_BASE_URL
)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Assistant</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 20px auto; padding: 0 10px; line-height: 1.6; }
        #chat { border: 1px solid #ccc; height: 400px; overflow-y: scroll; padding: 10px; margin-bottom: 10px; border-radius: 8px; background: #f9f9f9; }
        .message { margin-bottom: 10px; padding: 8px; border-radius: 5px; }
        .user { background: #e3f2fd; align-self: flex-end; }
        .assistant { background: #f1f8e9; }
        #input-container { display: flex; gap: 10px; }
        input { flex-grow: 1; padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
        button:disabled { background: #ccc; }
    </style>
</head>
<body>
    <h1>AI Assistant</h1>
    <div id="chat"></div>
    <div id="input-container">
        <input type="text" id="user-input" placeholder="Type your message..." autocomplete="off">
        <button id="send-btn">Send</button>
    </div>

    <script>
        const chat = document.getElementById('chat');
        const userInput = document.getElementById('user-input');
        const sendBtn = document.getElementById('send-btn');

        function appendMessage(role, text) {
            const div = document.createElement('div');
            div.className = 'message ' + role;
            div.textContent = text;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }

        async function sendMessage() {
            const text = userInput.value.trim();
            if (!text) return;

            appendMessage('user', text);
            userInput.value = '';
            userInput.disabled = true;
            sendBtn.disabled = true;

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });
                const data = await response.json();
                if (data.error) {
                    appendMessage('assistant', 'Error: ' + data.error);
                } else {
                    appendMessage('assistant', data.response);
                }
            } catch (e) {
                appendMessage('assistant', 'Error: Could not connect to server.');
            } finally {
                userInput.disabled = false;
                sendBtn.disabled = false;
                userInput.focus();
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        userInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": user_message}
            ],
            max_completion_tokens=8192
        )
        return jsonify({"response": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
