# LM Interactive Quiz (Anki Add‑on)

An Anki add‑on that lets you study a card with help from an LLM (OpenAI or a local LM Studio server). It opens a chat‑style dialog while you review, gives concise feedback on your answer based on the context given by the card.

## Quick start

### Install

- Download the 3 files from the repository and zip them.
- Start Anki
- Go to Tools/Add-ons
- Click 'Install from file' and select the zip file
- Restart Anki.
- Go to Tools/Configure LLM Quiz (Anki → Tools → Configure LLM Quiz)
- Either leave L< Studio if you have it setup, or choose OpenAI
- If OpenAI was chosen paste your API key and choose your model (e.g. gpt-4o).
- Set Question Field Index and Answer Field Index for your note type.
- Choose a system prompt if needed, using the 

### Use

While reviewing, click “Study with LLM” on a card.
Type your answer; the LLM evaluates it, gives brief feedback, and—if needed—asks one guiding question.

### Requirements

- Anki: modern desktop build (Qt6 era). The add‑on contains shims for both newer and older review APIs (see Compatibility below).

- Python: ships with Anki, you don’t need a separate install.

- LLM backend (choose one):

OpenAI API – requires an API key.

LM Studio – run a local server that mimics the OpenAI Chat Completions API (default: http://localhost:1234/v1/chat/completions).

