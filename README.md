# SPAR

Two AI agents beat the shit out of your ideas until a real gem survives. Then a VC tries to kill it.

5 agents. Full web research. No mercy.

| Agent | Role |
|---|---|
| 🔥 **EMBER** | Builder — pitches first, evolves ideas, pivots when killed |
| 🔪 **RAZOR** | Destroyer — attacks with competitor data, market evidence, fatal flaws |
| ⚖️ **JUDGE** | Gatekeeper — hard gates from GARBAGE to FUCKING BRILLIANT |
| 🐍 **VIPER** | VC — 8-point due diligence, INVEST / PASS / CONDITIONAL |
| 📋 **PITCH** | Synthesizer — compresses the session into a wall-pinnable summary |

## How it works

```
EMBER pitches → RAZOR attacks → JUDGE evaluates (every 2 rounds)
                                        ↓
                              If BRILLIANT → VIPER does VC review
                                        ↓
                              If rejected → back for more rounds
                                        ↓
                              PITCH summarizes everything at the end
```

All agents run on Claude Opus with extended thinking, full web research access, and shared conversation history.

## Install

```bash
pip install claude-agent-sdk rich
```

Requires [Claude Code](https://claude.ai/code) authenticated (Max subscription or API key).

## Usage

```bash
# Default: 12 rounds, exits on FUCKING BRILLIANT, 2 VC rejection cycles
python spar.py "your idea here"

# More rounds
python spar.py "your idea" --rounds 20

# Accept STRONG as exit threshold
python spar.py "your idea" --min-verdict strong

# More VC patience
python spar.py "your idea" --vc-rounds 4
```

Transcripts auto-save to `sparring_sessions/`.

## Customize agents

Edit the markdown files in `prompts/` — no code changes needed.

```
prompts/
├── research_protocol.md   # shared research rules (injected into EMBER, RAZOR, VIPER)
├── ember.md               # builder persona
├── razor.md               # destroyer persona
├── judge.md               # gatekeeper + hard gates
├── viper.md               # VC due diligence
└── pitch.md               # final summary format
```

## Example output

A session on "devops business idea in finance" ran 12 rounds, killed 8 ideas, and produced:

- **Dead**: generic consulting, trading infra, compliance SaaS, DORA services, GPU admission control, trading CI/CD, bot monitoring, AI governance
- **Survived**: Compliance infrastructure implementation practice — $6-10K fixed-price engagements bridging Vanta/Drata's 40-50% automation gap for fintechs with custom systems
- **Verdict**: STRONG (not BRILLIANT — hiring plan and breach liability never addressed)
- **Actionable**: Register for AWS Security Specialty, create Upwork profile, join Vanta Community Slack, email 3 audit firms

## License

MIT
