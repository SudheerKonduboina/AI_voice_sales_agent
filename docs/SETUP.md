# Setup Guide

## 1. Prerequisites

- Python 3.10+
- (Optional, for real LLM replies) [Ollama](https://ollama.com)
- (Optional, for real phone calls) A Twilio/LiveKit/Daily account + phone number
- (Optional, for orchestration) [n8n](https://n8n.io) — Community Edition (free, self-hosted)

## 2. Install Python dependencies

```bash
cd ai-voice-sales-agent
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Verify the CRM layer works

```bash
cd crm
python3 excel_crm.py
```

You should see the two Pending demo leads printed, then a simulated update
to lead L001 printed back out. Re-run `python3 make_template.py` any time
you want to reset `leads_template.xlsx` to its original demo state.

## 4. Run a simulated call (no external services required)

```bash
cd ../agent
python3 simulate_call.py --lead-id L001 --auto
```

This uses the offline rule-based fallback in `llm_client.py` since Ollama
isn't running yet — good enough to verify the full loop (conversation ->
extraction -> Excel write-back) works before adding real AI.

## 5. Add the real LLM

### Option A — `llama_cpp` (default): stays entirely inside the venv

No Ollama, no background service, no system-wide install — just a pip
package (`llama-cpp-python`) plus a model file.

```bash
# From step 2, llama-cpp-python and huggingface_hub are already installed
# via requirements.txt. Now fetch a model file:
python3 scripts/download_model.py

# On Windows, if pip fails to install llama-cpp-python with a build error,
# it means no prebuilt wheel matched your Python version — either upgrade
# pip first (`pip install --upgrade pip`) or install a matching wheel
# from https://github.com/abetlen/llama-cpp-python/releases

cd agent
python3 simulate_call.py --lead-id L001
```

The first call after starting the process will be slower (loading the
model file into memory); after that, replies come back in a few seconds
on a typical laptop CPU. If it feels too slow, edit `config/config.yaml`
-> `llm.llama_cpp.n_threads` up toward your CPU's core count, or run
`python3 scripts/download_model.py --model larger` for a bigger/better
model if you have 16GB+ RAM (update `model_path` in config.yaml to match).

### Option B — `ollama`: separate local server

```bash
# Install Ollama from https://ollama.com, then:
ollama pull llama3
ollama serve &
```
Set `llm.provider: "ollama"` in `config/config.yaml`, then re-run
`simulate_call.py`.

### Either way

Try typing an off-script question ("do you integrate with Slack?") — the
agent should answer using only `config/knowledge_base.md`, or say a team
member will follow up if it's not covered.

## 6. Add real speech (Whisper + Piper) — for local mic/speaker testing

This step lets you *talk* to the agent on your machine before wiring a
real phone line. It's not required for n8n/Excel integration to work.

```bash
pip install openai-whisper piper-tts
# Download a Piper voice, e.g.:
#   https://github.com/rhasspy/piper/releases -> en_US-lessac-medium
```

Wiring this into a live mic/speaker loop (as opposed to a phone call) is a
smaller version of what `voice_pipeline.py` does for phone audio — swap its
transport for a local audio I/O transport if you want this intermediate step.

## 7. Start the agent API (for n8n)

```bash
cd agent
uvicorn api:app --host 0.0.0.0 --port 8000
```

Test it:
```bash
curl http://localhost:8000/pending-leads
curl -X POST http://localhost:8000/call -H "Content-Type: application/json" \
     -d '{"lead_id": "L005", "mode": "simulate"}'
```

## 8. Import and run the n8n workflow

1. Start n8n: `npx n8n` (or your existing install)
2. Open the n8n UI -> Workflows -> Import from File
3. Select `n8n/voice_sales_agent_workflow.json`
4. Make sure `agent/api.py` is running at `http://localhost:8000` (step 7)
5. (Optional) Configure SMTP credentials for the "Notify Sales Team" node,
   or delete that node / swap it for Slack
6. Click "Execute Workflow" to run it once manually, or activate it to run
   on the hourly schedule

## 9. Going live with real phone calls

1. Pick a telephony provider (Twilio is the easiest starting point):
   - Sign up, buy a phone number, note your Account SID + Auth Token
   - Fill these into `.env` (copy from `.env.example`)
2. `pip install pipecat-ai[whisper,piper] twilio`
3. Open `agent/voice_pipeline.py` and follow the `# TODO` comments to
   construct the real Pipecat `Pipeline` with a Twilio Media Streams
   transport (or LiveKit/Daily — see comments for alternatives)
4. Switch the n8n workflow's `Call Lead (agent API)` node body from
   `"mode": "simulate"` to `"mode": "live"`
5. Test with a single lead before turning on the schedule for the full list

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `simulate_call.py` gives canned/repetitive replies | No LLM provider is reachable. For `llama_cpp`: confirm `models/` has the `.gguf` file and the path in `config.yaml` matches. For `ollama`: check `ollama serve` and `curl localhost:11434/api/tags` |
| `pip install llama-cpp-python` fails on Windows | No prebuilt wheel matched your Python version. Run `pip install --upgrade pip` first and retry; if it still fails, grab a matching wheel from https://github.com/abetlen/llama-cpp-python/releases |
| First call after starting is very slow | Expected — that's the GGUF model loading into memory. Subsequent calls in the same run are fast. |
| `ModuleNotFoundError: fastapi` | Run `pip install -r requirements.txt` inside your venv |
| n8n `Call Lead` node times out | Real calls can take minutes — the node's timeout is already set generously (8 min); increase in `n8n/voice_sales_agent_workflow.json` if needed |
| Excel file looks unchanged after a call | Confirm `config/config.yaml` -> `crm.excel_path` points at the file you're actually opening to check |
| Two processes both writing to the CRM at once | Don't run `call_runner.py` and the n8n workflow against the same Excel file simultaneously — openpyxl has no locking. Use `api.py` as the single writer. |
