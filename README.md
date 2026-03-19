<div align="center">

# SPAR

**5 AI agents beat the shit out of your ideas until a real gem survives.**

*Then a VC tries to kill it.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-required-orange.svg)](https://claude.ai/code)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

SPAR is an adversarial idea sparring tool powered by 5 autonomous AI agents. Each agent has a distinct role, does live web research, and fights with real evidence. Ideas get pressure-tested through multiple rounds of attack, defense, and evaluation — then face a VC due diligence review before earning a final verdict.

Every agent runs on **Claude Opus** with extended thinking, full web research access, and shared conversation history across all rounds.

Compatible with **Claude Max subscription** — no API key required.

## The Agents

| | Agent | Role | When |
|---|---|---|---|
| 🔥 | **EMBER** | Builder — researches, pitches, evolves ideas, pivots when killed | First, every round |
| 🔪 | **RAZOR** | Destroyer — finds competitors, market data, fatal flaws, proposes contradicting alternatives | Second, every round |
| ⚖️ | **JUDGE** | Gatekeeper — rates GARBAGE → WEAK → PROMISING → STRONG → FUCKING BRILLIANT with hard gates | Every 2 rounds |
| 🐍 | **VIPER** | VC — 8-point due diligence checklist, makes INVEST / PASS / CONDITIONAL decision | After JUDGE passes |
| 📋 | **PITCH** | Synthesizer — compresses the full session into a wall-pinnable summary with actionable next steps | End of session |

## How It Works

```
  🔥 EMBER pitches ──→ 🔪 RAZOR attacks ──→ ⚖️ JUDGE evaluates
        ↑                                          │
        │                                          │
        └──── repeat until BRILLIANT ◄─────────────┘
                                                   │
                                          If BRILLIANT ↓
                                                   │
                                      🐍 VIPER VC review
                                                   │
                              ┌────────────────────┼────────────────────┐
                              │                    │                    │
                          INVEST 💰          CONDITIONAL ⚠️          PASS ✗
                              │                    │                    │
                           done               more rounds          more rounds
                              │                    │                    │
                              └────────────────────┴────────────────────┘
                                                   │
                                          📋 PITCH summary
```

The JUDGE uses **hard gate requirements** — binary checkboxes that must ALL pass before a verdict can be awarded. For example, FUCKING BRILLIANT requires: real human voice validation, RAZOR failed to kill it, competitive moat stress-tested, 18-month plan modeled, and more. No hand-waving past the gates.

## Prerequisites

- **Python 3.10+**
- **[Claude Code](https://claude.ai/code)** — installed and authenticated

### Authentication

SPAR runs through the Claude Code CLI, so you authenticate the same way you authenticate Claude Code:

**With Claude Max subscription (recommended):**
```bash
claude          # opens browser for OAuth login — do this once
```

**With API key:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Both work. Max subscription means no per-token billing — your agents can research as aggressively as they want.

## Install

```bash
# Clone the repo
git clone https://github.com/sofianedjerbi/spar.git
cd spar

# Install dependencies
pip install claude-agent-sdk rich
```

That's it. No config files, no env setup, no Docker.

## Usage

```bash
# Default: 12 rounds, exits on FUCKING BRILLIANT, 2 VC rejection cycles
python spar.py "your idea here"

# More rounds for complex topics
python spar.py "your idea" --rounds 20

# Accept STRONG as exit threshold (less strict)
python spar.py "your idea" --min-verdict strong

# Give the VC more chances to reject and iterate
python spar.py "your idea" --vc-rounds 4

# Full gauntlet
python spar.py "your idea" --rounds 20 --vc-rounds 4 --min-verdict brilliant
```

Sessions auto-save timestamped transcripts to `sparring_sessions/`.

## Customize Agents

Every agent's personality, rules, and behavior are defined in standalone markdown files. Edit them directly — no code changes needed.

```
prompts/
├── research_protocol.md   # shared research budget + workflow (injected into EMBER, RAZOR, VIPER)
├── ember.md               # builder persona + creation protocol
├── razor.md               # destroyer persona + destruction protocol
├── judge.md               # gatekeeper + hard gate requirements + verdict scale
├── viper.md               # VC due diligence checklist + decision format
└── pitch.md               # final summary output format
```

Want a harsher JUDGE? Edit `judge.md`. Want RAZOR to focus on regulatory risk? Edit `razor.md`. Want to add a new gate requirement for BRILLIANT? Add a checkbox to `judge.md`. The `{RESEARCH_PROTOCOL}` placeholder in agent prompts gets replaced with `research_protocol.md` at runtime.

## Example Session

A session on *"devops business idea in finance"* ran 12 rounds, killed 8 ideas, and produced a validated business:

**The graveyard:**
- Generic DevOps consulting — commoditized, offshore shops undercut you
- Trading infrastructure — Citadel spends $100M/year on 1ms advantages
- Compliance-as-code SaaS — Checkov + 6 funded competitors already there
- DORA implementation services — bank procurement takes a year, you're subject to DORA yourself
- GPU admission controller — Kubecost, CAST AI, Sedai already shipping
- Trading CI/CD — Blankly built "QuantOps" and went dormant
- Trading bot monitoring — KillSwitch.in, ALGOGENE already shipping
- AI governance pivot — completely different career from DevOps

**The survivor:**
> Compliance infrastructure implementation practice — $6-10K fixed-price engagements bridging Vanta/Drata's 40-50% automation gap for fintechs with custom payment/fraud/KYC systems. Validated by Upwork marketplace demand (74 active compliance gigs) and EIM Services case study.

**Verdict:** STRONG (not BRILLIANT — hiring plan and breach liability never addressed in 12 rounds)

**Next steps generated:** Register for AWS Security Specialty, create Upwork profile targeting "SOC 2 compliance engineer Vanta", join Vanta Community Slack, publish LinkedIn post on custom Vanta integrations, email 3 SOC 2 audit firms.

## How It's Different

Most brainstorming tools accumulate enthusiasm. SPAR accumulates **earned conviction**.

- Every claim gets web-researched with real sources — no training data opinions
- Ideas that die get buried honestly with one-line kill reasons
- The JUDGE can't be charmed — hard gates are binary pass/fail
- EMBER catches RAZOR fabricating evidence (and vice versa)
- The final PITCH gives you something actionable, not a pep talk

## License

MIT
