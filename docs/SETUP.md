# Setup Guide (Windows, no assumptions)

This walks through everything needed to run `cycling-workout-engine-gemini`
from zero, assuming nothing is already installed or configured.

## 1. Get the code

Clone the repository with GitHub Desktop (File → Clone repository) or from
PowerShell:

```powershell
git clone https://github.com/infamemp/cycling-workout-engine-gemini C:\Dev\Github\cycling-workout-engine-gemini
cd C:\Dev\Github\cycling-workout-engine-gemini
```

Use a path with no spaces or accented characters. Every command below runs
from the repository's root folder (the one that contains `pedir.py`).

## 2. Check Python

Open **PowerShell** (Windows key → type `powershell` → Enter) and check your
Python version:

```powershell
python --version
```

Python 3.10 or newer is required. If it's not installed, get it from
[python.org](https://www.python.org/downloads/) or the Microsoft Store.

## 3. Install dependencies

```powershell
pip install -r requirements.txt
```

## 4. Run the test suite (no API key needed yet)

```powershell
python -m pytest -q
```

Every test should pass. The tests use a mock transport, not the real API, so
this step costs nothing and needs no key.

## 5. Try the deterministic offline mode

This uses the mechanical core only (no Gemini reasoning, so the workout will
be simple and generic). It confirms the pipeline produces valid output before
spending any API credit:

```powershell
python -m engine.cli --mode power --zone Tempo --duration 50
```

## 6. Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com) and sign in.
2. Open **Get API key** and create a key.
3. Copy the value. **Never share this key or paste it into a chat, prompt,
   or commit.** Treat it like a password.

## 7. Save the key as an environment variable (Windows, permanent)

In PowerShell, replace `YOUR_KEY_HERE` with your real key and run:

```powershell
[System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY', 'YOUR_KEY_HERE', 'User')
```

Close PowerShell completely and open a new window for the change to take
effect. Verify it saved (this only shows the key on your own screen — never
share this output):

```powershell
echo $env:GEMINI_API_KEY
```

## 8. Your thresholds (optional)

Copy the template and open it:

```powershell
copy athlete.example.yaml athlete.yaml
notepad athlete.yaml
```

Replace the example numbers with your own — the same values as in your
Intervals.icu settings — and save. The file is git-ignored, so it never
reaches GitHub. Without it, heart-rate workouts show their load as
approximate.

## 9. Generate your first real workout

```powershell
cd C:\Dev\Github\cycling-workout-engine-gemini
python pedir.py "resistencia aerobica de 1 hora"
```

You should see an interpretation confirmation, a short wait while Gemini
researches and reasons, and a complete workout in valid intervals.icu syntax,
saved to a `.md` file in the current folder.

## Model

The engine uses `gemini-3.8-flash` by default (see `engine/llm_config.py`).
To try another model without changing code, set `WORKOUT_ENGINE_MODEL` the
same way as the key in step 7.

## Troubleshooting

- **`python` not recognized** → Python isn't installed or isn't on PATH.
  Reinstall from python.org and check "Add Python to PATH" during setup.
- **`ModuleNotFoundError: No module named 'google'`** → re-run step 3.
- **Empty output from `echo $env:GEMINI_API_KEY`** → the variable didn't
  save, or you didn't open a *new* PowerShell window after setting it. Redo
  step 7.
- **404 mentioning "is not found for API version"** → the model was retired.
  Check [the current models](https://ai.google.dev/gemini-api/docs/models)
  and set `WORKOUT_ENGINE_MODEL` to a current one.
- **API errors mentioning authentication or quota** → the key may be invalid,
  or the project may need billing enabled in Google AI Studio.
