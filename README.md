# Digital Wingman

<p align="center">
  <img src="docs/assets/hingeauto-wordmark.png" alt="Digital Wingman" width="680">
</p>

<p align="center">
  <strong>See the profile. Understand the person. Start a better conversation.</strong><br>
  A human-in-the-loop, vision-powered dating profile analysis pipeline for thoughtful compatibility and specific conversation starters.
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-ff4fd8.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-45%20passing-2ea44f.svg">
  <img alt="Platforms" src="https://img.shields.io/badge/platforms-Hinge%20%C2%B7%20Bumble%20%C2%B7%20Tinder%20%C2%B7%20Happn-8b5cf6.svg">
  <img alt="Human in the loop" src="https://img.shields.io/badge/human--in--the--loop-required-f59e0b.svg">
</p>

<p align="center">
  <a href="#why-digital-wingman">Why it exists</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#use-it-with-any-dating-platform">Platforms</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## Why Digital Wingman?

Most dating tools optimize for volume: more swipes, more messages, more noise.
Digital Wingman takes the opposite approach.

It helps you answer three better questions:

1. **Is there a realistic compatibility signal here?**
2. **What specific detail could lead to a natural conversation?**
3. **Can I say something that sounds like me instead of an AI template?**

The project combines multi-frame vision analysis, deterministic evidence
merging, compatibility rules, hook extraction, opener generation, and a
human approval step. It is designed as an AI engineering project and a
personal experimentation framework, not as a replacement for judgment,
consent, or authentic interaction.

## Who is this for?

Digital Wingman is a good fit if you are:

- building with multimodal LLMs and want a practical vision pipeline;
- interested in structured extraction from changing mobile UI screenshots;
- experimenting with compatibility rubrics and conversational UX;
- tired of generic openers and want specific, profile-grounded suggestions;
- comfortable reviewing AI output before using it;
- curious about building a reusable analysis layer across multiple apps.

It is **not** a good fit if you want a blind auto-swiper, mass messaging bot,
or a system that decides how to manipulate people. The default configuration
is dry-run and human-approved.

## What it does

Given one or more screenshots of a dating profile, Digital Wingman:

1. extracts only visible profile evidence;
2. merges repeated observations across frames;
3. separates prompts, photos, interests, and basic information;
4. scores profile effort and identifies conversation hooks;
5. evaluates compatibility against your private profile and rubric;
6. generates a small set of specific opener candidates;
7. shows the recommendation for human review;
8. optionally records feedback for later experiments.

The reusable analysis pipeline works with saved screenshots from Hinge,
Bumble, Tinder, Happn, or another dating platform. Hinge has an optional ADB
capture/action adapter. Other platforms currently use manual screenshot import.

## Safety and privacy first

### Human approval is the default

The project is configured for `dry_run` with human approval enabled. AI
recommendations are suggestions, not instructions. You choose whether to
send anything.

### Keep personal data local

Never commit:

- `.env` files or API keys;
- profile screenshots;
- your private profile YAML;
- self-profile scans;
- experiment history;
- match or conversation logs.

The repository includes [`data/user_profile.example.yaml`](data/user_profile.example.yaml).
Copy it to `data/aryan_profile.yaml` and customize it locally. Personal data
paths are ignored by Git.

### Respect people and platform rules

Do not use the project to harass, spam, deceive, impersonate, pressure, or
target people using sensitive traits. Follow the terms of every platform you
use and applicable privacy law. Hinge ADB automation may violate Hinge's Terms
of Service and can result in account restrictions. The safest supported
workflow is screenshot analysis plus manual action.

## How it works

```text
screenshots or optional Hinge capture
                 |
                 v
       bounded frame collection
                 |
                 v
      visible evidence extraction
                 |
                 v
    duplicate-aware deterministic merge
                 |
                 v
      conversation hook discovery
                 |
                 v
      compatibility evaluation
                 |
                 v
       opener candidates + reasons
                 |
                 v
        human review and feedback
```

Capture is deliberately bounded. The default profile capture uses at most
eight frames, keeps only changed frames, and stops after stable screens. This
prevents unnecessary vision calls and makes offline debugging practical.

## Quickstart

### Requirements

- Python 3.10 or newer;
- Git;
- an LLM backend:
  - Gemini API, or
  - Anthropic API, or
  - local/cloud Ollama;
- Android SDK Platform Tools and an emulator only if using Hinge ADB capture;
- screenshots or saved frames for offline multi-platform testing.

### Install

```bash
git clone <your-repository-url>
cd digital-wingman

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For Ollama:

```bash
.venv/bin/python -m pip install -r requirements-ollama.txt
```

### Configure the private profile

```bash
cp data/user_profile.example.yaml data/aryan_profile.yaml
cp .env.example .env
```

Edit `data/aryan_profile.yaml` with your own goals, communication style,
boundaries, and preferences. It is ignored by Git.

Choose a backend in `.env` or `config.py`:

```env
JUDGE_BACKEND=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

For Anthropic:

```env
JUDGE_BACKEND=anthropic
ANTHROPIC_API_KEY=your-key-here
```

For local Ollama, set `JUDGE_BACKEND=ollama`, install the optional dependency,
start Ollama, and pull a vision model:

```bash
ollama serve
ollama pull qwen2.5-vl
```

### Verify the installation

```bash
.venv/bin/python verify_setup.py
```

An ADB warning is expected when you are testing imported screenshots without
a connected device.

## Use it with any dating platform

The platform label changes the analysis context only. It does not claim that
the tool understands every private UI detail or automate every app.

### Saved screenshot analysis

Put screenshots in a directory named `frame_00.png`, `frame_01.png`, and so
on, then run:

```bash
.venv/bin/python wingman_session.py \
  --frames-dir debug/profile_frames \
  --platform bumble \
  --no-approval
```

Supported labels:

```text
generic  hinge  bumble  tinder  happn
```

Examples:

```bash
# Tinder screenshots
.venv/bin/python wingman_session.py \
  --frames-dir samples/tinder_profile \
  --platform tinder \
  --no-approval

# Happn screenshots
.venv/bin/python wingman_session.py \
  --frames-dir samples/happn_profile \
  --platform happn \
  --no-approval

# Re-run from cached extraction data without another vision pass
.venv/bin/python wingman_session.py \
  --frames-dir debug/profile_frames \
  --platform bumble \
  --judge-only \
  --no-approval
```

### Hinge capture

Hinge capture requires:

- Android Studio or another Android emulator;
- Hinge installed in the emulator;
- the app open on a profile;
- `adb devices` showing exactly one connected device, unless
  `config.ADB_SERIAL` is set locally;
- calibrated coordinates for your screen.

Start with a safe capture:

```bash
adb devices
.venv/bin/python wingman_session.py --live-capture --single-frame
```

For full bounded capture:

```bash
.venv/bin/python wingman_session.py --live-capture --platform hinge
```

Non-Hinge live ADB capture is intentionally blocked until separate adapters
are implemented and tested. Use screenshot import for those platforms.

## Modes and personalization

Modes live in [`modes/`](modes/). The repository includes generic examples:

- [`example_lenient.py`](modes/example_lenient.py)
- [`example_strict.py`](modes/example_strict.py)

To create your own:

```bash
cp modes/example_strict.py modes/my_mode.py
```

Then set `ACTIVE_MODE = "my_mode"` in `config.py`.

Voices live in [`voice/`](voice/). Use a voice name from your mode or provide
a literal voice rubric. Keep your personal mode and voice ignored if they
contain identity-specific information.

## Architecture

| Component | Responsibility |
|---|---|
| [`wingman_session.py`](wingman_session.py) | CLI entry point and session orchestration |
| [`wingman/capture.py`](wingman/capture.py) | Bounded screenshot capture and frame persistence |
| [`wingman/profile_analyzer.py`](wingman/profile_analyzer.py) | Per-frame visible evidence extraction |
| [`wingman/merge_frames.py`](wingman/merge_frames.py) | Deterministic duplicate-aware profile merge |
| [`wingman/hooks.py`](wingman/hooks.py) | Conversation hook extraction and ranking |
| [`wingman/compatibility.py`](wingman/compatibility.py) | Compatibility rubric and structured decision |
| [`wingman/opener.py`](wingman/opener.py) | Grounded opener candidates and validation |
| [`wingman/platforms.py`](wingman/platforms.py) | Supported platform labels and normalization |
| [`wingman/pipeline.py`](wingman/pipeline.py) | Stage orchestration and checkpoint resume |
| [`judge_*.py`](.) | LLM backend adapters |
| [`tests/`](tests/) | Offline regression tests |

Checkpoint artifacts are stored under a local debug directory and allow
expensive stages to be resumed without repeating every model call.

## Useful commands

```bash
# Run all tests
.venv/bin/python -m pytest -q

# Validate Python syntax
.venv/bin/python -m compileall -q .

# Inspect setup and optional backend connectivity
.venv/bin/python verify_setup.py --check-backend

# Generate a deterministic merged profile from cached frame JSON
.venv/bin/python wingman_session.py \
  --frames-dir debug/profile_frames \
  --merge-only

# Regenerate only openers from cached downstream checkpoints
.venv/bin/python wingman_session.py \
  --frames-dir debug/profile_frames \
  --openers-only
```

## Troubleshooting

### `No ADB device found`

Start the emulator, enable USB debugging if using a phone, then run:

```bash
adb devices
```

If multiple devices appear, set `ADB_SERIAL` locally in `config.py`.

### Too many screenshots

Check `DISCOVER_PROFILE_MAX_FRAMES` and `SELF_PROFILE_MAX_FRAMES` in
`config.py`. The default capture stops after stable frames and stores only
changed frames. Use `--single-frame` to validate the rest of the pipeline
without scrolling.

### Ollama returns malformed JSON

Try a smaller frame set first:

```bash
.venv/bin/python wingman_session.py \
  --frames-dir debug/profile_frames \
  --platform generic \
  --single-frame \
  --no-approval
```

Then compare the saved checkpoint output. Larger vision models generally
handle structured extraction better than very small models.

### Missing private profile

Copy the template:

```bash
cp data/user_profile.example.yaml data/aryan_profile.yaml
```

Then edit it locally. Do not commit the copied file.

## Roadmap

- [x] Human-in-the-loop analysis pipeline
- [x] Bounded, duplicate-aware frame capture
- [x] Deterministic multi-frame merging
- [x] Compatibility and opener stages
- [x] Offline screenshot import
- [x] Platform labels for Hinge, Bumble, Tinder, and Happn
- [ ] Improve Ollama structured-output reliability
- [ ] Add anonymized cross-platform screenshot fixtures
- [ ] Add platform-specific extraction hints without coupling the core pipeline
- [ ] Add dedicated, opt-in capture adapters with clear safety gates
- [ ] Add experiment reports for reply and conversation outcomes

## Contributing

Small, focused pull requests are welcome. Before opening one:

1. do not include screenshots, API keys, private profile data, or chat logs;
2. add or update an offline test;
3. run `pytest`, `compileall`, and `git diff --check`;
4. describe which platform and backend you tested;
5. document any behavior change.

## License

MIT. See [`LICENSE`](LICENSE).

This project is for educational and experimental use. You are responsible for
your account, your data, your messages, and compliance with applicable
platform terms.
