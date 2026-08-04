# Discord Ollama Bot

A Python Discord bot that sends chat messages to an Ollama server on your local network. It responds in direct messages, when mentioned in a server, or when someone replies to one of its messages.

## 1. Make Ollama reachable on the LAN

On the computer running Ollama, make it listen beyond localhost. The exact way you make environment variables persistent depends on its operating system.

```text
OLLAMA_HOST=0.0.0.0:11434
```

Restart Ollama, pull the model you want, and note that computer's local IP address. Make sure its firewall permits inbound TCP traffic on port `11434` from your local network only.

Test from the computer that will run the bot:

```bash
curl http://192.168.1.50:11434/api/tags
```

Replace the example IP with the Ollama computer's address.

## 2. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application.
2. Open **Bot**, create the bot, and copy/reset its token.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
4. Open **OAuth2 > URL Generator**. Select the `bot` scope and grant **View Channels**, **Send Messages**, **Read Message History**, and **Add Reactions**.
5. Open the generated URL and add the bot to your server.

## 3. Configure and run

Python 3.11–3.13 is recommended. The pinned `aiohttp` version may require local
compiler tools on Python 3.14 because a prebuilt package may not be available.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set the Discord token and Ollama endpoint near the top of `config.toml`:

```toml
discord_token = "paste-your-discord-bot-token-here"
ollama_url = "http://192.168.1.50:11434"
```

Use the Ollama computer's LAN address and port without adding `/api/chat`. Keep this file private after inserting the real Discord token.

For deployments where values should come from the environment, `DISCORD_TOKEN` and `OLLAMA_URL` in `.env` override their corresponding `config.toml` settings.

Set the default Ollama model near the top of `config.toml`:

```toml
default_model = "llama3.2"
```

Use the exact name shown by `ollama list` on the Ollama server. The model must already be installed there.

### Select a personality

Edit `config.toml` and set `active_personality` to one of the personality names in the file:

```toml
active_personality = "pirate"

[personalities.pirate]
system_prompt = """
You are a cheerful pirate assistant. Remain helpful and concise.
"""
```

The optional `model` setting lets a personality use a different installed Ollama model. When it is omitted, the personality uses `default_model` from the top of `config.toml`:

```toml
[personalities.technical]
model = "qwen2.5-coder:7b"
system_prompt = "You are a pragmatic senior software engineer."
```

Restart the bot after changing the selection or definitions. Invalid configuration stops the bot with a descriptive error instead of silently using the wrong personality.

### Configure conversation memory

Set `memory_size` near the top of `config.toml`:

```toml
memory_size = 20
```

This is the maximum number of previous messages sent between users and the bot that are included when generating the next reply. For example, `20` normally represents the last 10 user-and-bot exchanges. The system personality prompt does not count toward this limit.

Memory is maintained separately for each Discord channel or direct-message conversation and is stored in memory only. Set the value to `0` to make every request independent. Restart the bot after changing it.

### Configure streaming speed

Ollama responses are streamed into Discord by progressively updating the bot's
message. While waiting for the first text, Discord's typing indicator is shown;
the bot does not post a placeholder message. The update interval is configurable
in `config.toml`:

```toml
stream_update_interval = 0.75
```

The value is measured in seconds and must be at least `0.25`. Lower values look
more responsive but cause more Discord API requests.

Start the bot:

```bash
python bot.py
```

Run the automated tests with the virtual environment active:

```bash
python -m unittest -v
```

This includes a local integration test that constructs the real Discord client,
calls a mock Ollama `/api/chat` endpoint, and verifies conversation memory. It
does not contact Discord or your configured Ollama server.

In a server, send `@YourBot hello`. In a direct message, just type normally. The bot includes the configured number of earlier exchanges from that same channel when asking Ollama for its next reply.

After the bot responds, the immediately following message in that channel is
treated as a continuation even if it does not mention the bot or use Discord's
reply feature. If another message appears first, mention or reply to the bot to
start interacting with it again. This requires **Read Message History** permission.

- `!reset` clears the current channel's conversation history.
- `!memory` reports how many messages are currently remembered and the configured limit.
- `!personality` shows the active personality.

History is lost when the process restarts.

## Notes

- Keep any file containing the Discord token private; the token grants control of the bot.
- Ollama has no authentication in this setup. Keep port `11434` accessible only on your trusted LAN.
- Each Discord channel gets separate context. Simultaneous requests in the same channel are processed in order.
- Users see only a neutral temporary-failure message when something goes wrong; technical error details are written to the bot's console logs.
